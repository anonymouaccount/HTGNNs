# -*- coding: utf-8 -*-
"""HTGNN_Last.fm.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1TCN54N2eDNZ1r4xedCUGvL6TUTA0rzBD
"""

!pip install torch-geometric

# Step 1: Mount Google Drive
from google.colab import drive
drive.mount('/content/drive')

# Step 2: Unzip the Last.fm.zip file
import zipfile
zip_path = '/content/drive/MyDrive/Last.FM.zip'
with zipfile.ZipFile(zip_path, 'r') as zip_ref:
    zip_ref.extractall('/content/lastfm_data')

# Step 3: Load the extracted CSV
import pandas as pd

csv_path = '/content/lastfm_data/Last.fm_data.csv'
df = pd.read_csv(csv_path)

# Step 4: Process the data
df['timestamp'] = pd.to_datetime(df['Date'] + ' ' + df['Time'])
df.rename(columns={'Username': 'user_id', 'Track': 'item_id'}, inplace=True)
df.dropna(subset=['user_id', 'item_id', 'timestamp'], inplace=True)
df = df.sort_values(by='timestamp')

# Optional: preview
df.head()

from sklearn.model_selection import train_test_split

# Split into training and testing
train_data, test_data = train_test_split(df, test_size=0.2, shuffle=False)

# Graph creation
import networkx as nx

def create_graph(data):
    G = nx.DiGraph()
    for _, row in data.iterrows():
        G.add_edge(row['user_id'], row['item_id'], timestamp=row['timestamp'].timestamp())
    return G

train_graph = create_graph(train_data)
test_graph = create_graph(test_data)

import torch
from torch_geometric.data import Data, DataLoader
import torch.nn.functional as F
from torch_geometric.nn import GCNConv

def convert_to_pyg_data(graph, num_features=8):
    nodes = list(graph.nodes())
    node_mapping = {node: i for i, node in enumerate(nodes)}
    edge_index = torch.tensor([[node_mapping[u], node_mapping[v]] for u, v in graph.edges]).t().contiguous()
    edge_time = torch.tensor([graph[u][v]['timestamp'] for u, v in graph.edges], dtype=torch.float)
    x = torch.randn(len(nodes), num_features)
    y = torch.randint(0, 2, (len(nodes),))  # Placeholder labels
    return Data(x=x, edge_index=edge_index, edge_time=edge_time, y=y)

train_data_pyg = convert_to_pyg_data(train_graph)
test_data_pyg = convert_to_pyg_data(test_graph)

train_loader = DataLoader([train_data_pyg], batch_size=1, shuffle=True)
test_loader = DataLoader([test_data_pyg], batch_size=1, shuffle=False)

class HTGNN(torch.nn.Module):
    def __init__(self, in_channels, out_channels):
        super(HTGNN, self).__init__()
        self.conv1 = GCNConv(in_channels, 8)
        self.conv2 = GCNConv(8 + 8, out_channels)
        self.time_embedding = torch.nn.Embedding(365, 8)

    def forward(self, x, edge_index, edge_time):
        print(f'Input x shape: {x.shape}')
        print(f'Edge index shape: {edge_index.shape}')
        print(f'Edge time shape: {edge_time.shape}')

        x = self.conv1(x, edge_index)
        x = F.relu(x)
        print(f'x after conv1 shape: {x.shape}')

        # Embedding for the edge times
        time_embeds = self.time_embedding((edge_time.long() % 365).view(-1, 1)).view(-1, 8)
        print(f'time_embeds shape: {time_embeds.shape}')

        # Average the edge time embeddings per node
        node_time_embeds = torch.zeros_like(x)
        for i in range(edge_index.size(1)):
            node_time_embeds[edge_index[0, i]] += time_embeds[i]
        print(f'node_time_embeds shape: {node_time_embeds.shape}')

        x = torch.cat([x, node_time_embeds], dim=1)
        print(f'x after concatenation shape: {x.shape}')

        x = self.conv2(x, edge_index)
        print(f'x after conv2 shape: {x.shape}')

        return x

# Initialize the model, loss function, and optimizer
model = HTGNN(in_channels=train_data_pyg.num_node_features, out_channels=2)
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
loss_fn = torch.nn.CrossEntropyLoss()

# Training function
def train(model, loader, optimizer, loss_fn):
    model.train()
    total_loss = 0
    for data in loader:
        optimizer.zero_grad()
        out = model(data.x, data.edge_index, data.edge_time)
        loss = loss_fn(out, data.y)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    return total_loss / len(loader)

# Evaluation function
def evaluate(model, loader):
    model.eval()
    correct = 0
    for data in loader:
        out = model(data.x, data.edge_index, data.edge_time)
        pred = out.argmax(dim=1)
        correct += (pred == data.y).sum().item()
    return correct / len(loader.dataset)

# Training loop
for epoch in range(100):
    train_loss = train(model, train_loader, optimizer, loss_fn)
    test_acc = evaluate(model, test_loader)
    print(f'Epoch {epoch}, Loss: {train_loss}, Test Accuracy: {test_acc}')

import numpy as np
from sklearn.metrics import precision_score, recall_score, f1_score, accuracy_score
from sklearn.preprocessing import label_binarize

# Function to calculate MRR
def mrr_score(y_true, y_pred):
    order = np.argsort(y_pred)[::-1]
    ranks = np.where(y_true[order] == 1)[0] + 1
    return np.mean(1.0 / ranks)

# Function to calculate NDCG
def ndcg_score(y_true, y_pred, k=10):
    order = np.argsort(y_pred)[::-1]
    y_true = np.take(y_true, order[:k])

    gains = 2 ** y_true - 1
    discounts = np.log2(np.arange(2, k + 2))
    dcg = np.sum(gains / discounts)

    ideal_gains = 2 ** np.sort(y_true)[::-1] - 1
    idcg = np.sum(ideal_gains / discounts)

    return dcg / idcg if idcg > 0 else 0.0

# Evaluation function with metrics
def evaluate_with_metrics(model, loader):
    model.eval()
    all_preds = []
    all_labels = []
    for data in loader:
        out = model(data.x, data.edge_index, data.edge_time)
        pred = out.argmax(dim=1)
        all_preds.append(pred.detach().cpu().numpy())
        all_labels.append(data.y.detach().cpu().numpy())

    all_preds = np.concatenate(all_preds)
    all_labels = np.concatenate(all_labels)

    accuracy = accuracy_score(all_labels, all_preds)
    precision = precision_score(all_labels, all_preds, average='macro')
    recall = recall_score(all_labels, all_preds, average='macro')
    f1 = f1_score(all_labels, all_preds, average='macro')
    mrr = mrr_score(all_labels, all_preds)
    ndcg = ndcg_score(all_labels, all_preds)

    return accuracy, precision, recall, f1, mrr, ndcg

# Function to calculate just the accuracy
def calculate_accuracy(model, loader):
    model.eval()
    correct = 0
    total = 0
    for data in loader:
        out = model(data.x, data.edge_index, data.edge_time)
        pred = out.argmax(dim=1)
        correct += (pred == data.y).sum().item()
        total += data.y.size(0)
    accuracy = correct / total
    return accuracy

accuracy, precision, recall, f1, mrr, ndcg = evaluate_with_metrics(model, test_loader)
print(f' NDCG: {ndcg}, Precision: {precision}, Recall: {recall}, F1-Score: {f1}')

accuracy = calculate_accuracy(model, test_loader)
print(f'Final Accuracy: {accuracy}')

"""# GraphSAGE + Last.**fm**"""

# Step 1: Mount Google Drive
from google.colab import drive
drive.mount('/content/drive')

# Step 2: Unzip the Last.fm dataset
import zipfile
zip_path = '/content/drive/MyDrive/Last.FM.zip'
with zipfile.ZipFile(zip_path, 'r') as zip_ref:
    zip_ref.extractall('/content/lastfm_data')

# Step 3: Load and preprocess Last.fm data
import pandas as pd
import os

csv_path = '/content/lastfm_data/Last.fm_data.csv'
df = pd.read_csv(csv_path)

df['timestamp'] = pd.to_datetime(df['Date'] + ' ' + df['Time'])
df.rename(columns={'Username': 'user_id', 'Track': 'item_id'}, inplace=True)
df.dropna(subset=['user_id', 'item_id', 'timestamp'], inplace=True)
df = df.sort_values(by='timestamp')

# Optional: Filter most active users
top_users = df['user_id'].value_counts().head(1000).index
df = df[df['user_id'].isin(top_users)]

# Step 4: Split into train/test and create graphs
from sklearn.model_selection import train_test_split
import networkx as nx

train_data, test_data = train_test_split(df, test_size=0.2, shuffle=False)

def create_graph(data):
    G = nx.DiGraph()
    for _, row in data.iterrows():
        G.add_edge(row['user_id'], row['item_id'], timestamp=row['timestamp'].timestamp())
    return G

train_graph = create_graph(train_data)
test_graph = create_graph(test_data)

# Step 5: Convert to PyTorch Geometric format
import torch
from torch_geometric.data import Data, DataLoader

def convert_to_pyg_data(graph, num_features=8):
    nodes = list(graph.nodes())
    node_mapping = {node: i for i, node in enumerate(nodes)}
    edge_index = torch.tensor([[node_mapping[u], node_mapping[v]] for u, v in graph.edges], dtype=torch.long).t().contiguous()
    x = torch.randn(len(nodes), num_features)
    y = torch.randint(0, 2, (len(nodes),))  # Placeholder binary labels
    return Data(x=x, edge_index=edge_index, y=y)

train_data_pyg = convert_to_pyg_data(train_graph)
test_data_pyg = convert_to_pyg_data(test_graph)

train_loader = DataLoader([train_data_pyg], batch_size=1, shuffle=True)
test_loader = DataLoader([test_data_pyg], batch_size=1, shuffle=False)

# Step 6: Define GraphSAGE model
import torch.nn.functional as F
from torch_geometric.nn import SAGEConv

class GraphSAGE(torch.nn.Module):
    def __init__(self, in_channels, out_channels):
        super(GraphSAGE, self).__init__()
        self.conv1 = SAGEConv(in_channels, 8)
        self.conv2 = SAGEConv(8, out_channels)

    def forward(self, x, edge_index):
        x = self.conv1(x, edge_index)
        x = F.relu(x)
        x = self.conv2(x, edge_index)
        return x

# Step 7: Initialize model, loss, optimizer
model = GraphSAGE(in_channels=train_data_pyg.num_node_features, out_channels=2)
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
loss_fn = torch.nn.CrossEntropyLoss()

# Step 8: Training and Evaluation
def train(model, loader, optimizer, loss_fn):
    model.train()
    total_loss = 0
    for data in loader:
        optimizer.zero_grad()
        out = model(data.x, data.edge_index)
        loss = loss_fn(out, data.y)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    return total_loss / len(loader)

def evaluate(model, loader):
    model.eval()
    correct = 0
    for data in loader:
        out = model(data.x, data.edge_index)
        pred = out.argmax(dim=1)
        correct += (pred == data.y).sum().item()
    return correct / len(loader.dataset)

# Run training
for epoch in range(10):
    loss = train(model, train_loader, optimizer, loss_fn)
    acc = evaluate(model, test_loader)
    print(f"Epoch {epoch+1}, Loss: {loss:.4f}, Accuracy: {acc:.4f}")

# Step 9: Final Evaluation with Metrics
import numpy as np
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

def mrr_score(y_true, y_pred_probs):
    # For MRR, we need the probability scores for positive class
    y_true = np.array(y_true)
    y_pred_probs = np.array(y_pred_probs)

    # Get the rank of each positive example
    ranks = []
    for i in np.where(y_true == 1)[0]:
        # Get the score of the positive example
        score = y_pred_probs[i]
        # Count how many examples have higher score than this positive example
        rank = (y_pred_probs > score).sum() + 1
        ranks.append(rank)

    if len(ranks) == 0:
        return 0.0
    return np.mean(1.0 / np.array(ranks))

def ndcg_score(y_true, y_pred_probs, k=10):
    # Sort by predicted probabilities in descending order
    order = np.argsort(y_pred_probs)[::-1]
    y_true_sorted = np.array(y_true)[order[:k]]

    # Calculate DCG
    gains = 2 ** y_true_sorted - 1
    discounts = np.log2(np.arange(2, k + 2))
    dcg = np.sum(gains / discounts)

    # Calculate IDCG
    ideal_gains = 2 ** np.sort(y_true)[::-1][:k] - 1
    idcg = np.sum(ideal_gains / discounts)

    return dcg / idcg if idcg > 0 else 0.0

# Updated evaluation function with metrics
def evaluate_with_metrics(model, loader):
    model.eval()
    all_preds = []
    all_probs = []
    all_labels = []

    for data in loader:
        out = model(data.x, data.edge_index)
        probs = F.softmax(out, dim=1)
        pred = out.argmax(dim=1)

        all_preds.append(pred.detach().cpu().numpy())
        all_probs.append(probs[:, 1].detach().cpu().numpy())  # Probability of positive class
        all_labels.append(data.y.detach().cpu().numpy())

    all_preds = np.concatenate(all_preds)
    all_probs = np.concatenate(all_probs)
    all_labels = np.concatenate(all_labels)

    accuracy = accuracy_score(all_labels, all_preds)
    precision = precision_score(all_labels, all_preds, average='macro', zero_division=0)
    recall = recall_score(all_labels, all_preds, average='macro', zero_division=0)
    f1 = f1_score(all_labels, all_preds, average='macro', zero_division=0)
    mrr = mrr_score(all_labels, all_probs)
    ndcg = ndcg_score(all_labels, all_probs)

    return accuracy, precision, recall, f1, mrr, ndcg

accuracy, precision, recall, f1, mrr, ndcg = evaluate_with_metrics(model, test_loader)
print(f'NDCG: {ndcg:.4f}, Precision: {precision:.4f}, Recall: {recall:.4f}, F1: {f1:.4f}, MRR: {mrr:.4f}, Accuracy: {accuracy:.4f}')

"""# TGN + Last.**fm**"""

# Step 1: Mount Google Drive
from google.colab import drive
drive.mount('/content/drive')

# Step 2: Unzip Last.fm dataset
import zipfile
zip_path = '/content/drive/MyDrive/Last.FM.zip'
with zipfile.ZipFile(zip_path, 'r') as zip_ref:
    zip_ref.extractall('/content/lastfm_data')

# Step 3: Load and preprocess data
import pandas as pd
csv_path = '/content/lastfm_data/Last.fm_data.csv'
df = pd.read_csv(csv_path)

df['timestamp'] = pd.to_datetime(df['Date'] + ' ' + df['Time'])
df.rename(columns={'Username': 'user_id', 'Track': 'item_id'}, inplace=True)
df.dropna(subset=['user_id', 'item_id', 'timestamp'], inplace=True)
df = df.sort_values(by='timestamp')

# Filter active users (top 1000)
top_users = df['user_id'].value_counts().head(1000).index
df = df[df['user_id'].isin(top_users)]

# Step 4: Create train/test and graphs
from sklearn.model_selection import train_test_split
import networkx as nx

train_data, test_data = train_test_split(df, test_size=0.2, shuffle=False)

def create_graph(data):
    G = nx.DiGraph()
    for _, row in data.iterrows():
        G.add_edge(row['user_id'], row['item_id'], timestamp=row['timestamp'].timestamp())
    return G

train_graph = create_graph(train_data)
test_graph = create_graph(test_data)

# Step 5: Convert to PyG format
import torch
from torch_geometric.data import Data, DataLoader

def convert_to_pyg_data(graph, num_features=8):
    nodes = list(graph.nodes())
    node_mapping = {node: i for i, node in enumerate(nodes)}
    edge_index = torch.tensor([[node_mapping[u], node_mapping[v]] for u, v in graph.edges], dtype=torch.long).t().contiguous()
    edge_time = torch.tensor([graph[u][v]['timestamp'] for u, v in graph.edges], dtype=torch.float)
    x = torch.randn(len(nodes), num_features)
    y = torch.randint(0, 2, (len(nodes),))  # Placeholder binary labels
    return Data(x=x, edge_index=edge_index, edge_time=edge_time, y=y)

train_data_pyg = convert_to_pyg_data(train_graph)
test_data_pyg = convert_to_pyg_data(test_graph)

train_loader = DataLoader([train_data_pyg], batch_size=1, shuffle=True)
test_loader = DataLoader([test_data_pyg], batch_size=1, shuffle=False)

# Step 6: Define TGN model
import torch.nn as nn
import torch.nn.functional as F

class TGNModel(nn.Module):
    def __init__(self, in_channels, out_channels, memory_dim=8, time_dim=8):
        super(TGNModel, self).__init__()
        self.memory_dim = memory_dim
        self.time_dim = time_dim

        self.memory = torch.zeros(10000, memory_dim)  # dynamic size handled below

        self.time_embedding = nn.Embedding(365, time_dim)
        self.message_fn = nn.Linear(in_channels + memory_dim + time_dim, memory_dim)
        self.memory_update_fn = nn.GRUCell(memory_dim, memory_dim)
        self.fc = nn.Linear(memory_dim, out_channels)

    def forward(self, x, edge_index, edge_time):
        num_nodes = x.size(0)
        if self.memory.size(0) < num_nodes:
            # Expand memory if needed
            new_memory = torch.zeros(num_nodes, self.memory_dim)
            new_memory[:self.memory.size(0)] = self.memory
            self.memory = new_memory

        src, dst = edge_index
        src_memory = self.memory[src]
        dst_memory = self.memory[dst]
        time_embeds = self.time_embedding((edge_time.long() % 365).view(-1, 1)).view(-1, self.time_dim)

        messages = self.message_fn(torch.cat([x[src], src_memory, time_embeds], dim=1))
        updated_memory = self.memory_update_fn(messages, dst_memory)
        self.memory[dst] = updated_memory.detach()

        out = self.fc(updated_memory)
        return out

# Step 7: Train and evaluate
model = TGNModel(in_channels=train_data_pyg.num_node_features, out_channels=2)
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
loss_fn = nn.CrossEntropyLoss()

def train(model, loader, optimizer, loss_fn):
    model.train()
    total_loss = 0
    for data in loader:
        optimizer.zero_grad()
        out = model(data.x, data.edge_index, data.edge_time)
        loss = loss_fn(out, data.y[data.edge_index[1]])
        loss.backward(retain_graph=True)
        optimizer.step()
        total_loss += loss.item()
    return total_loss / len(loader)

def evaluate(model, loader):
    model.eval()
    correct, total = 0, 0
    for data in loader:
        out = model(data.x, data.edge_index, data.edge_time)
        pred = out.argmax(dim=1)
        correct += (pred == data.y[data.edge_index[1]]).sum().item()
        total += len(data.edge_index[1])
    return correct / total

for epoch in range(10):
    loss = train(model, train_loader, optimizer, loss_fn)
    acc = evaluate(model, test_loader)
    print(f"Epoch {epoch+1}, Loss: {loss:.4f}, Accuracy: {acc:.4f}")

# Step 9: Final Evaluation with Metrics
import numpy as np
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

def mrr_score(y_true, y_pred_probs):
    # For MRR, we need the probability scores for positive class
    y_true = np.array(y_true)
    y_pred_probs = np.array(y_pred_probs)

    # Get the rank of each positive example
    ranks = []
    for i in np.where(y_true == 1)[0]:
        # Get the score of the positive example
        score = y_pred_probs[i]
        # Count how many examples have higher score than this positive example
        rank = (y_pred_probs > score).sum() + 1
        ranks.append(rank)

    if len(ranks) == 0:
        return 0.0
    return np.mean(1.0 / np.array(ranks))

def ndcg_score(y_true, y_pred_probs, k=10):
    # Sort by predicted probabilities in descending order
    order = np.argsort(y_pred_probs)[::-1]
    y_true_sorted = np.array(y_true)[order[:k]]

    # Calculate DCG
    gains = 2 ** y_true_sorted - 1
    discounts = np.log2(np.arange(2, k + 2))
    dcg = np.sum(gains / discounts)

    # Calculate IDCG
    ideal_gains = 2 ** np.sort(y_true)[::-1][:k] - 1
    idcg = np.sum(ideal_gains / discounts)

    return dcg / idcg if idcg > 0 else 0.0

# Step 9: Final Evaluation with Metrics
import numpy as np
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

def mrr_score(y_true, y_pred_probs):
    y_true = np.array(y_true)
    y_pred_probs = np.array(y_pred_probs)

    ranks = []
    for i in np.where(y_true == 1)[0]:
        score = y_pred_probs[i]
        rank = (y_pred_probs > score).sum() + 1
        ranks.append(rank)

    if len(ranks) == 0:
        return 0.0
    return np.mean(1.0 / np.array(ranks))

def ndcg_score(y_true, y_pred_probs, k=10):
    order = np.argsort(y_pred_probs)[::-1]
    y_true_sorted = np.array(y_true)[order[:k]]

    gains = 2 ** y_true_sorted - 1
    discounts = np.log2(np.arange(2, k + 2))
    dcg = np.sum(gains / discounts)

    ideal_gains = 2 ** np.sort(y_true)[::-1][:k] - 1
    idcg = np.sum(ideal_gains / discounts)

    return dcg / idcg if idcg > 0 else 0.0

def evaluate_with_metrics(model, loader):
    model.eval()
    all_preds = []
    all_probs = []
    all_labels = []

    for data in loader:
        # Include edge_time in the forward pass
        out = model(data.x, data.edge_index, data.edge_time)
        probs = F.softmax(out, dim=1)
        pred = out.argmax(dim=1)

        # Get the labels for the destination nodes (where predictions are made)
        dst_nodes = data.edge_index[1]
        dst_labels = data.y[dst_nodes]

        all_preds.append(pred.detach().cpu().numpy())
        all_probs.append(probs[:, 1].detach().cpu().numpy())  # Probability of positive class
        all_labels.append(dst_labels.detach().cpu().numpy())

    if len(all_preds) == 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

    all_preds = np.concatenate(all_preds)
    all_probs = np.concatenate(all_probs)
    all_labels = np.concatenate(all_labels)

    # Handle case where there are no positive examples
    if len(np.unique(all_labels)) == 1:
        precision = 0.0 if 1 not in all_labels else 1.0
        recall = 0.0 if 1 not in all_labels else 1.0
        f1 = 0.0 if 1 not in all_labels else 1.0
    else:
        precision = precision_score(all_labels, all_preds, average='macro', zero_division=0)
        recall = recall_score(all_labels, all_preds, average='macro', zero_division=0)
        f1 = f1_score(all_labels, all_preds, average='macro', zero_division=0)

    accuracy = accuracy_score(all_labels, all_preds)
    mrr = mrr_score(all_labels, all_probs)
    ndcg = ndcg_score(all_labels, all_probs)

    return accuracy, precision, recall, f1, mrr, ndcg

accuracy, precision, recall, f1, mrr, ndcg = evaluate_with_metrics(model, test_loader)
print(f'NDCG: {ndcg:.4f}, Precision: {precision:.4f}, Recall: {recall:.4f}, F1: {f1:.4f}, MRR: {mrr:.4f}, Accuracy: {accuracy:.4f}')

"""# RNN + Last.**fm**"""

# Step 1: Mount Google Drive
from google.colab import drive
drive.mount('/content/drive')

# Step 2: Unzip the Last.fm dataset
import zipfile
zip_path = '/content/drive/MyDrive/Last.FM.zip'
with zipfile.ZipFile(zip_path, 'r') as zip_ref:
    zip_ref.extractall('/content/lastfm_data')

# Step 3: Load and preprocess Last.fm
import pandas as pd
csv_path = '/content/lastfm_data/Last.fm_data.csv'
df = pd.read_csv(csv_path)

df['timestamp'] = pd.to_datetime(df['Date'] + ' ' + df['Time'])
df.rename(columns={'Username': 'user_id', 'Track': 'item_id'}, inplace=True)
df.dropna(subset=['user_id', 'item_id', 'timestamp'], inplace=True)
df = df.sort_values(by='timestamp')

# Filter most active users
top_users = df['user_id'].value_counts().head(1000).index
df = df[df['user_id'].isin(top_users)]

# Step 4: Split and create graphs
from sklearn.model_selection import train_test_split
import networkx as nx

train_data, test_data = train_test_split(df, test_size=0.2, shuffle=False)

def create_graph(data):
    G = nx.DiGraph()
    for _, row in data.iterrows():
        G.add_edge(row['user_id'], row['item_id'], timestamp=row['timestamp'].timestamp())
    return G

train_graph = create_graph(train_data)
test_graph = create_graph(test_data)

# Step 5: Convert to PyTorch Geometric format
import torch
from torch_geometric.data import Data, DataLoader

def convert_to_pyg_data(graph, num_features=8):
    nodes = list(graph.nodes())
    node_mapping = {node: i for i, node in enumerate(nodes)}
    edge_index = torch.tensor([[node_mapping[u], node_mapping[v]] for u, v in graph.edges], dtype=torch.long).t().contiguous()
    edge_time = torch.tensor([graph[u][v]['timestamp'] for u, v in graph.edges], dtype=torch.float)
    x = torch.randn(len(nodes), num_features)
    y = torch.randint(0, 2, (len(nodes),))  # Placeholder binary labels
    return Data(x=x, edge_index=edge_index, edge_time=edge_time, y=y)

train_data_pyg = convert_to_pyg_data(train_graph)
test_data_pyg = convert_to_pyg_data(test_graph)

train_loader = DataLoader([train_data_pyg], batch_size=1, shuffle=True)
test_loader = DataLoader([test_data_pyg], batch_size=1, shuffle=False)

# Step 6: Define RNN model
import torch.nn as nn
import torch.nn.functional as F

class RNNModel(nn.Module):
    def __init__(self, input_size, hidden_size, output_size):
        super(RNNModel, self).__init__()
        self.hidden_size = hidden_size
        self.rnn = nn.RNN(input_size, hidden_size, batch_first=True)
        self.fc = nn.Linear(hidden_size, output_size)

    def forward(self, x, edge_index, edge_time):
        sorted_indices = torch.argsort(edge_time)
        sorted_edge_index = edge_index[:, sorted_indices]
        src = sorted_edge_index[0]
        sequences = x[src]
        batch_size = sequences.size(0)
        h0 = torch.zeros(1, batch_size, self.hidden_size)
        out, _ = self.rnn(sequences.unsqueeze(1), h0)
        out = self.fc(out.squeeze(1))
        return out

# Step 7: Train and Evaluate
model = RNNModel(input_size=train_data_pyg.num_node_features, hidden_size=16, output_size=2)
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
loss_fn = nn.CrossEntropyLoss()

def train(model, loader, optimizer, loss_fn):
    model.train()
    total_loss = 0
    for data in loader:
        optimizer.zero_grad()
        out = model(data.x, data.edge_index, data.edge_time)
        loss = loss_fn(out, data.y[data.edge_index[1]])
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    return total_loss / len(loader)

def evaluate(model, loader):
    model.eval()
    correct = 0
    total = 0
    for data in loader:
        out = model(data.x, data.edge_index, data.edge_time)
        pred = out.argmax(dim=1)
        correct += (pred == data.y[data.edge_index[1]]).sum().item()
        total += len(data.edge_index[1])
    return correct / total

for epoch in range(10):
    train_loss = train(model, train_loader, optimizer, loss_fn)
    test_acc = evaluate(model, test_loader)
    print(f"Epoch {epoch+1}, Loss: {train_loss:.4f}, Accuracy: {test_acc:.4f}")

# Step 8: Metrics
import numpy as np
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

def mrr_score(y_true, y_pred_probs):
    y_true = np.array(y_true)
    y_pred_probs = np.array(y_pred_probs)
    ranks = []
    for i in np.where(y_true == 1)[0]:
        score = y_pred_probs[i]
        rank = (y_pred_probs > score).sum() + 1
        ranks.append(rank)
    return np.mean(1.0 / np.array(ranks)) if ranks else 0.0

def ndcg_score(y_true, y_pred_probs, k=10):
    order = np.argsort(y_pred_probs)[::-1]
    y_true_sorted = np.array(y_true)[order[:k]]
    gains = 2 ** y_true_sorted - 1
    discounts = np.log2(np.arange(2, k + 2))
    dcg = np.sum(gains / discounts)
    ideal_gains = 2 ** np.sort(y_true)[::-1][:k] - 1
    idcg = np.sum(ideal_gains / discounts)
    return dcg / idcg if idcg > 0 else 0.0

def evaluate_with_metrics(model, loader):
    model.eval()
    all_preds, all_probs, all_labels = [], [], []
    for data in loader:
        out = model(data.x, data.edge_index, data.edge_time)
        probs = F.softmax(out, dim=1)
        pred = out.argmax(dim=1)
        dst = data.edge_index[1]
        labels = data.y[dst]
        all_preds.append(pred.detach().cpu().numpy())
        all_probs.append(probs[:, 1].detach().cpu().numpy())
        all_labels.append(labels.detach().cpu().numpy())

    all_preds = np.concatenate(all_preds)
    all_probs = np.concatenate(all_probs)
    all_labels = np.concatenate(all_labels)

    accuracy = accuracy_score(all_labels, all_preds)
    precision = precision_score(all_labels, all_preds, average='macro', zero_division=0)
    recall = recall_score(all_labels, all_preds, average='macro', zero_division=0)
    f1 = f1_score(all_labels, all_preds, average='macro', zero_division=0)
    mrr = mrr_score(all_labels, all_probs)
    ndcg = ndcg_score(all_labels, all_probs)

    return accuracy, precision, recall, f1, mrr, ndcg

accuracy, precision, recall, f1, mrr, ndcg = evaluate_with_metrics(model, test_loader)
print(f"NDCG: {ndcg:.4f}, Precision: {precision:.4f}, Recall: {recall:.4f}, F1: {f1:.4f}, MRR: {mrr:.4f}, Accuracy: {accuracy:.4f}")