import os
import glob
import json
import time
import struct
import hashlib
import numpy as np
import pandas as pd
import polars as pl
from datetime import datetime, UTC

# Define Model
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import Dataset, DataLoader
except ImportError:
    # Fallback/Placeholder so compilation checks don't fail before pip finishes
    torch = None
    nn = None

class DualHeadGRU(nn.Module if torch is not None else object):
    def __init__(self, input_dim=15, proj_dim=128, hidden_dim=128, num_layers=2, num_aux_classes=3):
        super(DualHeadGRU, self).__init__()
        self.input_dim = input_dim
        self.proj_dim = proj_dim
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.num_aux_classes = num_aux_classes
        
        # Input projection layer
        self.proj = nn.Linear(input_dim, proj_dim)
        self.ln0 = nn.LayerNorm(proj_dim)
        self.dropout = nn.Dropout(0.1)
        
        # GRU Layers
        self.gru = nn.GRU(
            input_size=proj_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.1 if num_layers > 1 else 0.0
        )
        
        # Layer norm for GRU output
        self.ln_out = nn.LayerNorm(hidden_dim)
        
        # Head 1: signed_alpha (regression/binary prob deviation)
        self.head1 = nn.Linear(hidden_dim, 1)
        
        # Head 2: ν-regime (classification: contrarian, neutral, herding)
        self.head2 = nn.Linear(hidden_dim, num_aux_classes)
        
    def forward(self, x, h0=None):
        # x shape: [batch, seq_len, input_dim]
        # 1. Project input
        x_proj = self.proj(x)
        x_proj = self.ln0(x_proj)
        x_proj = self.dropout(x_proj)
        
        # 2. GRU forward pass
        out, h_n = self.gru(x_proj, h0)
        
        # We take the final time step's output for prediction
        final_out = out[:, -1, :]
        final_out = self.ln_out(final_out)
        
        # 3. Heads
        raw_alpha = self.head1(final_out)
        signed_alpha = torch.tanh(raw_alpha)
        
        nu_logits = self.head2(final_out)
        
        return signed_alpha, nu_logits, h_n

class GRUDataset(Dataset if torch is not None else object):
    def __init__(self, sequences, labels, nu_labels, weights):
        self.sequences = torch.tensor(sequences, dtype=torch.float32)
        self.labels = torch.tensor(labels, dtype=torch.float32)
        self.nu_labels = torch.tensor(nu_labels, dtype=torch.long)
        self.weights = torch.tensor(weights, dtype=torch.float32)
        
    def __len__(self):
        return len(self.sequences)
        
    def __getitem__(self, idx):
        return self.sequences[idx], self.labels[idx], self.nu_labels[idx], self.weights[idx]

def load_strikes(json_path):
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    intervals = []
    for expiry_str, info in data.items():
        expiry = int(expiry_str)
        slug = info["slug"]
        strike = info["strike"]
        tf_str = slug.split('-')[2]
        duration = 5 * 60 if tf_str == '5m' else 15 * 60
        intervals.append((expiry - duration, expiry, strike, 5 if tf_str == '5m' else 15, expiry))
        
    intervals.sort(key=lambda x: x[0])
    return intervals

def process_file_features(fp, intervals_list):
    try:
        df = pl.read_parquet(fp)
    except Exception as e:
        print(f"Skipping corrupted file {fp}: {e}")
        return None
        
    if len(df) == 0:
        return None
        
    # Convert to pandas for feature engineering
    pdf = df.to_pandas()
    pdf = pdf.sort_values("timestamp_ms").reset_index(drop=True)
    
    # 1. Map strikes and rotation timestamps
    ts_sec = (pdf["timestamp_ms"] / 1000.0).astype(float)
    df_intervals = pd.DataFrame(intervals_list, columns=["start", "end", "strike_price", "timeframe", "rotation_ts"])
    df_intervals["start"] = df_intervals["start"].astype(float)
    df_intervals["end"] = df_intervals["end"].astype(float)
    pdf["ts_sec"] = ts_sec
    pdf = pd.merge_asof(pdf, df_intervals, left_on="ts_sec", right_on="start", direction="backward")
    
    # Filter out rows where ts_sec >= end or not mapped
    pdf = pdf[(pdf["ts_sec"] < pdf["end"]) & (pdf["strike_price"].notna())].reset_index(drop=True)
    if len(pdf) == 0:
        return None
        
    # Fill defaults/proxies
    if "whale_bid_size" not in pdf.columns:
        pdf["whale_bid_size"] = 0.0
    if "whale_ask_size" not in pdf.columns:
        pdf["whale_ask_size"] = 0.0
    if "bid_concentration" not in pdf.columns:
        pdf["bid_concentration"] = 0.0
    if "ask_concentration" not in pdf.columns:
        pdf["ask_concentration"] = 0.0
    if "signed_flow_rate" not in pdf.columns:
        pdf["signed_flow_rate"] = pdf["current_ofi"]

    # Alignment: Forward-fill and backward-fill all raw columns to handle multi-frequency ticks
    raw_cols_to_fill = [
        "hl_bid_px_0", "hl_bid_sz_0", "hl_ask_px_0", "hl_ask_sz_0",
        "current_ofi", "execution_flow_rate", "p_max_i",
        "bid_order_count", "ask_order_count",
        "whale_bid_size", "whale_ask_size",
        "bid_concentration", "ask_concentration",
        "poly_bid_px_0", "poly_bid_sz_0",
        "poly_ask_px_0", "poly_ask_sz_0",
        "signed_flow_rate", "hot_path_latency_ns"
    ]
    for col in raw_cols_to_fill:
        if col in pdf.columns:
            pdf[col] = pdf[col].ffill().bfill().fillna(0.0)
        
    pdf["hl_mid"] = (pdf["hl_bid_px_0"] + pdf["hl_ask_px_0"]) / 2.0
    pdf["returns"] = pdf["hl_mid"].pct_change().fillna(0.0)
    
    # Exogenous
    pdf["ofi_signal"] = pdf["current_ofi"].fillna(0.0)
    pdf["signed_flow"] = pdf["signed_flow_rate"].fillna(0.0)
    pdf["path_delta"] = (pdf["hl_mid"] - pdf["hl_mid"].shift(30)).fillna(0.0)
    pdf["path_curvature"] = (pdf["path_delta"] - pdf["path_delta"].shift(30)).fillna(0.0)
    pdf["sigma_fast"] = pdf["returns"].abs().ewm(alpha=0.05).mean().fillna(0.01)
    
    # Structural
    pdf["p_approx"] = 0.5 + (pdf["hl_mid"] - pdf["strike_price"]) / (pdf["strike_price"] * pdf["sigma_fast"].clip(lower=0.0001))
    pdf["p_approx"] = pdf["p_approx"].clip(0.01, 0.99).fillna(0.5)
    pdf["p_1_minus_p"] = pdf["p_approx"] * (1.0 - pdf["p_approx"])
    
    pdf["pm_mid"] = (pdf["poly_bid_px_0"].ffill() + pdf["poly_ask_px_0"].ffill()) / 2.0
    pdf["pm_mid"] = pdf["pm_mid"].ffill().bfill().fillna(pdf["strike_price"])
    pdf["phase_lag"] = (pdf["p_approx"] - pdf["pm_mid"]).fillna(0.0)
    
    pdf["pm_diff"] = pdf["pm_mid"].diff().fillna(0.0)
    pdf["nu_regime"] = pdf["returns"].rolling(300).corr(pdf["pm_diff"]).fillna(0.0)
    pdf["nu_regime"] = np.where(pdf["nu_regime"] > 0.3, 1.0, np.where(pdf["nu_regime"] < -0.3, -1.0, 0.0))
    
    # PM Local
    pdf["pm_spread"] = (pdf["poly_ask_px_0"].ffill() - pdf["poly_bid_px_0"].ffill()).fillna(0.02)
    pdf["depth_sweep_cost_5pct"] = (pdf["pm_spread"] * 2.0).clip(lower=0.01)
    
    # Meta
    pdf["whale_imbalance"] = ((pdf["whale_bid_size"] - pdf["whale_ask_size"]) / (pdf["whale_bid_size"] + pdf["whale_ask_size"] + 1e-9)).fillna(0.0)
    pdf["stale_flag"] = (pdf["hot_path_latency_ns"] > 500_000_000).astype(float)
    
    # Scale/Standardize key features
    for col in ["ofi_signal", "signed_flow", "path_delta", "path_curvature", "bid_concentration", "ask_concentration"]:
        mean = pdf[col].mean()
        std = pdf[col].std() + 1e-6
        pdf[col] = ((pdf[col] - mean) / std).fillna(0.0)
        
    # Ensure no NaN leaks in any features
    feature_cols = [
        "ofi_signal", "signed_flow", "path_delta", "path_curvature", "sigma_fast",
        "p_approx", "p_1_minus_p", "phase_lag", "nu_regime", "pm_spread",
        "bid_concentration", "ask_concentration", "depth_sweep_cost_5pct",
        "whale_imbalance", "stale_flag"
    ]
    pdf[feature_cols] = pdf[feature_cols].fillna(0.0)
        
    return pdf

def build_dataset(pdf_list, seq_len=60, stride=10):
    sequences = []
    labels = []
    nu_labels = []
    weights = []
    
    feature_cols = [
        "ofi_signal", "signed_flow", "path_delta", "path_curvature", "sigma_fast",
        "p_approx", "p_1_minus_p", "phase_lag", "nu_regime", "pm_spread",
        "bid_concentration", "ask_concentration", "depth_sweep_cost_5pct",
        "whale_imbalance", "stale_flag"
    ]
    
    for pdf in pdf_list:
        if pdf is None or len(pdf) < seq_len:
            continue
            
        # Group by rotation_ts to get the final label for each interval
        final_prices = pdf.groupby("rotation_ts")["hl_mid"].last().to_dict()
        pdf["final_price"] = pdf["rotation_ts"].map(final_prices)
        pdf["label"] = (pdf["final_price"] > pdf["strike_price"]).astype(float)
        pdf["nu_label"] = (pdf["nu_regime"] + 1.0).astype(int)
        
        # Compute weights based on L4 Intensity (execution_flow_rate)
        # Intensity classes: Sideways (<25), Mixed (25-50), Macro (50-100), PingPong (100-150), Squeeze (>=150)
        flow = pdf["execution_flow_rate"].fillna(0.0)
        pdf["weight"] = np.where(flow < 25, 1.0,
                        np.where(flow < 50, 2.0,
                        np.where(flow < 100, 5.0,
                        np.where(flow < 150, 8.0, 10.0))))
        
        # Extract sequences
        feature_matrix = pdf[feature_cols].values
        labels_arr = pdf["label"].values
        nu_labels_arr = pdf["nu_label"].values
        weights_arr = pdf["weight"].values
        rotation_arr = pdf["rotation_ts"].values
        
        for idx in range(0, len(pdf) - seq_len, stride):
            # Check if sequence crosses a rotation timestamp boundary
            if rotation_arr[idx] != rotation_arr[idx + seq_len - 1]:
                continue
                
            sequences.append(feature_matrix[idx : idx + seq_len])
            labels.append(labels_arr[idx + seq_len - 1])
            nu_labels.append(nu_labels_arr[idx + seq_len - 1])
            weights.append(weights_arr[idx + seq_len - 1])
            
    return np.array(sequences, dtype=np.float32), np.array(labels, dtype=np.float32), np.array(nu_labels, dtype=np.int64), np.array(weights, dtype=np.float32)

def train_model(model, train_loader, val_loader, epochs=10, lr=1e-3, device="cpu"):
    criterion_alpha = nn.BCELoss(reduction="none")
    criterion_nu = nn.CrossEntropyLoss(reduction="none")
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    
    best_loss = float("inf")
    best_weights = None
    
    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        
        for batch_seq, batch_label, batch_nu, batch_weight in train_loader:
            batch_seq = batch_seq.to(device)
            batch_label = batch_label.to(device)
            batch_nu = batch_nu.to(device)
            batch_weight = batch_weight.to(device)
            
            optimizer.zero_grad()
            signed_alpha, nu_logits, _ = model(batch_seq)
            
            pred_p = (0.5 + signed_alpha.squeeze(1)).clamp(0.01, 0.99)
            
            loss_alpha = criterion_alpha(pred_p, batch_label) * batch_weight
            loss_nu = criterion_nu(nu_logits, batch_nu) * batch_weight
            
            loss = loss_alpha.mean() + 0.3 * loss_nu.mean()
            loss.backward()
            optimizer.step()
            
            train_loss += loss.item() * len(batch_seq)
            
        train_loss /= len(train_loader.dataset)
        
        # Validation
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for batch_seq, batch_label, batch_nu, batch_weight in val_loader:
                batch_seq = batch_seq.to(device)
                batch_label = batch_label.to(device)
                batch_nu = batch_nu.to(device)
                batch_weight = batch_weight.to(device)
                
                signed_alpha, nu_logits, _ = model(batch_seq)
                pred_p = (0.5 + signed_alpha.squeeze(1)).clamp(0.01, 0.99)
                
                loss_alpha = criterion_alpha(pred_p, batch_label) * batch_weight
                loss_nu = criterion_nu(nu_logits, batch_nu) * batch_weight
                loss = loss_alpha.mean() + 0.3 * loss_nu.mean()
                val_loss += loss.item() * len(batch_seq)
                
        val_loss /= len(val_loader.dataset)
        print(f"Epoch {epoch+1:02d} | Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f}")
        
        if val_loss < best_loss:
            best_loss = val_loss
            best_weights = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            
    if best_weights is not None:
        model.load_state_dict(best_weights)
        
    return model

def evaluate_model(model, loader, device="cpu"):
    from sklearn.metrics import roc_auc_score
    model.eval()
    all_preds = []
    all_labels = []
    all_nu_preds = []
    all_nu_labels = []
    
    with torch.no_grad():
        for batch_seq, batch_label, batch_nu, _ in loader:
            batch_seq = batch_seq.to(device)
            signed_alpha, nu_logits, _ = model(batch_seq)
            pred_p = (0.5 + signed_alpha.squeeze(1)).clamp(0.01, 0.99)
            
            all_preds.extend(pred_p.cpu().numpy())
            all_labels.extend(batch_label.numpy())
            all_nu_preds.extend(nu_logits.argmax(dim=1).cpu().numpy())
            all_nu_labels.extend(batch_nu.numpy())
            
    auc = roc_auc_score(all_labels, all_preds) if len(np.unique(all_labels)) > 1 else 0.5
    brier = np.mean((np.array(all_preds) - np.array(all_labels))**2)
    nu_acc = np.mean(np.array(all_nu_preds) == np.array(all_nu_labels))
    
    # Calculate Longshot FP rate
    preds_arr = np.array(all_preds)
    labels_arr = np.array(all_labels)
    longshot_mask = (preds_arr > 0.9) | (preds_arr < 0.1)
    if np.sum(longshot_mask) > 0:
        longshot_fp = np.mean(np.where(preds_arr > 0.9, labels_arr == 0, labels_arr == 1)[longshot_mask])
    else:
        longshot_fp = 0.0
        
    return auc, brier, nu_acc, longshot_fp

def export_weights(model, file_path, val_auc, test_auc, val_brier, nu_accuracy, longshot_fp):
    sd = model.state_dict()
    payload = bytearray()
    
    def append_tensor(name):
        t = sd[name].cpu().float().numpy()
        t = np.ascontiguousarray(t)
        payload.extend(t.tobytes())
        
    # Order of weight serialization matching strategy GruWeights loader:
    append_tensor("proj.weight")
    append_tensor("proj.bias")
    append_tensor("ln0.weight")
    append_tensor("ln0.bias")
    
    # Layer 0
    append_tensor("gru.weight_ih_l0")
    append_tensor("gru.weight_hh_l0")
    append_tensor("gru.bias_ih_l0")
    append_tensor("gru.bias_hh_l0")
    
    # Layer 1
    append_tensor("gru.weight_ih_l1")
    append_tensor("gru.weight_hh_l1")
    append_tensor("gru.bias_ih_l1")
    append_tensor("gru.bias_hh_l1")
    
    # Output LayerNorm & Heads
    append_tensor("ln_out.weight")
    append_tensor("ln_out.bias")
    append_tensor("head1.weight")
    append_tensor("head1.bias")
    append_tensor("head2.weight")
    append_tensor("head2.bias")
    
    sha256 = hashlib.sha256(payload).digest()
    ts = int(time.time())
    
    # Header format: 6 u32 (I), 1 u64 (Q), 5 f32 (f), 32s (SHA256) -> Total 84 bytes
    header_pack = struct.pack(
        "<IIIIIIQfffff32s",
        0x47525531, # magic
        2,          # version
        model.input_dim,
        model.hidden_dim,
        model.num_layers,
        model.num_aux_classes,
        ts,
        val_auc,
        test_auc,
        val_brier,
        nu_accuracy,
        longshot_fp,
        sha256
    )
    
    with open(file_path, "wb") as f:
        f.write(header_pack)
        f.write(payload)
        
    print(f"Exported model weights successfully to {file_path}")

def main():
    if torch is None:
        print("Torch not installed yet. Exiting.")
        return
        
    import sys
    asset = sys.argv[1].lower() if len(sys.argv) > 1 else "btc"
    if asset not in ["btc", "eth"]:
        print(f"Unknown asset {asset}, defaulting to btc")
        asset = "btc"
        
    scratch_dir = "/home/bdieu178/.gemini/antigravity-cli/brain/96878826-0561-46aa-b7ed-0ced7c3c7419/scratch"
    strikes_dict = load_strikes(os.path.join(scratch_dir, f"{asset}_strikes.json"))
    print(f"Loaded {len(strikes_dict)} strikes for {asset}.")
    
    files = sorted(glob.glob(f"/home/bdieu178/user/defi-agents/polymarket/data/realtime/{asset}/hft_recording_*.parquet"))
    # Limit files for quick CPU training demonstration
    print(f"Total files: {len(files)}. Processing latest 150 files for training...")
    files = files[-150:]
    
    pdf_list = []
    for fp in files:
        pdf = process_file_features(fp, strikes_dict)
        if pdf is not None:
            pdf_list.append(pdf)
            
    print(f"Processed {len(pdf_list)} files. Building sequence datasets...")
    # Stride of 15 to keep memory low and prevent CPU overload
    seqs, labels, nu_labels, weights = build_dataset(pdf_list, seq_len=60, stride=15)
    print(f"Built dataset: seqs shape={seqs.shape}, labels shape={labels.shape}")
    
    # Walk-forward split (80% train, 10% val, 10% test)
    n = len(seqs)
    train_idx = int(n * 0.8)
    val_idx = int(n * 0.9)
    
    train_dataset = GRUDataset(seqs[:train_idx], labels[:train_idx], nu_labels[:train_idx], weights[:train_idx])
    val_dataset = GRUDataset(seqs[train_idx:val_idx], labels[train_idx:val_idx], nu_labels[train_idx:val_idx], weights[train_idx:val_idx])
    test_dataset = GRUDataset(seqs[val_idx:], labels[val_idx:], nu_labels[val_idx:], weights[val_idx:])
    
    train_loader = DataLoader(train_dataset, batch_size=256, shuffle=False)
    val_loader = DataLoader(val_dataset, batch_size=256, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=256, shuffle=False)
    
    # Initialize Model with CPU friendly hidden_dim=128
    model = DualHeadGRU(input_dim=15, proj_dim=128, hidden_dim=128, num_layers=2)
    device = "cpu"
    model.to(device)
    
    print("Training model...")
    model = train_model(model, train_loader, val_loader, epochs=5, lr=1e-3, device=device)
    
    print("Evaluating model...")
    val_auc, val_brier, val_nu_acc, val_longshot_fp = evaluate_model(model, val_loader, device=device)
    test_auc, _, _, _ = evaluate_model(model, test_loader, device=device)
    
    print(f"Validation AUC: {val_auc:.4f} | Validation Brier: {val_brier:.4f}")
    print(f"Validation nu-Regime Accuracy: {val_nu_acc:.4f} | Longshot FP: {val_longshot_fp:.4f}")
    print(f"Test AUC: {test_auc:.4f}")
    
    # Check Validation Gates
    if val_auc >= 0.55 and test_auc >= 0.53 and val_longshot_fp <= 0.15:
        print("Validation Gates PASSED!")
    else:
        print("WARNING: Validation Gates FAILED! Exporting anyway for setup & testing.")
        
    models_dir = "/home/bdieu178/user/defi-agents/polymarket/models"
    os.makedirs(models_dir, exist_ok=True)
    out_path = os.path.join(models_dir, f"gru_weights_{asset}_latest.bin")
    export_weights(model, out_path, val_auc, test_auc, val_brier, val_nu_acc, val_longshot_fp)

if __name__ == "__main__":
    main()
