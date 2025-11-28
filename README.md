# Prometheus Cardinality Explorer

A 3D visualization tool for discovering high cardinality metrics by parsing raw Prometheus exposition format from `/metrics` endpoints.

## The Problem

High cardinality metrics can cause:
- Memory issues in Prometheus/Thanos
- Slow queries
- Increased storage costs

Finding the source is hard when label names are generic (like `_label_0`, `_label_1`).

## The Solution

This tool:
1. **Parses** raw Prometheus metrics from any `/metrics` endpoint
2. **Builds a tree** where root = metric name, children = label key/values
3. **Visualizes** in 3D so you can see where cardinality explodes
4. **Shows actual values** so even with generic labels you can identify patterns

## Quick Start

### Option 1: From a /metrics Endpoint

```bash
# Fetch from your application's metrics endpoint
python3 fetch_metrics.py --url http://your-app:8080/metrics

# Start visualization
python3 -m http.server 8080
# Open http://localhost:8080
```

### Option 2: From a Saved Metrics File

```bash
# If you have a metrics dump
python3 fetch_metrics.py --file ./metrics.txt

python3 -m http.server 8080
```

### Option 3: Try with Sample Data

```bash
python3 fetch_metrics.py --sample
python3 -m http.server 8080
```

## Usage

```
python3 fetch_metrics.py [OPTIONS]

Source (one required):
  --url URL              Fetch from a /metrics endpoint
  --file, -f FILE        Load from a local file
  --sample               Generate sample data for testing

Options:
  --output, -o FILE      Output JSON file (default: metrics_tree.json)
  --top, -n N            Number of top metrics to process (default: 50)
  --min-series N         Minimum series count to include (default: 1)
  --bearer-token TOKEN   Bearer token for authentication
  --basic-auth USER:PASS Basic auth credentials
  --timeout SECONDS      Request timeout (default: 30)
  --save-raw FILE        Save raw metrics for debugging
```

### Examples

```bash
# Basic usage
python3 fetch_metrics.py --url http://localhost:8080/metrics

# With auth
python3 fetch_metrics.py --url http://app:8080/metrics --bearer-token $TOKEN

# Top 100 metrics, save raw data
python3 fetch_metrics.py --url http://app:8080/metrics --top 100 --save-raw raw.txt

# From file, minimum 10 series per metric
python3 fetch_metrics.py --file metrics.txt --min-series 10
```

## Visualization Controls

| Control | Action |
|---------|--------|
| **Click** | Select a node |
| **Scroll** | Zoom in/out |
| **Drag** | Rotate view |
| **R** | Reset camera |
| **Search** | Filter nodes by label value |

## Understanding the Tree

```
http_requests_total (root) → 50K series
├── _label_0="us-east-1" → 12K series
│   ├── _label_1="api" → 3K series
│   │   └── _label_2="user-12345" → 100 series  ← PROBLEM: user IDs!
│   └── _label_1="web" → 2K series
└── _label_0="eu-west-1" → 15K series
    └── ... (explosion visible here)
```

### Node Colors
- 🟢 **Green**: Low cardinality (<100 series)
- 🟡 **Yellow**: Medium cardinality (100-1000 series)
- 🔴 **Red**: High cardinality (>1000 series)

## Common High Cardinality Patterns

| Pattern | Example Values | Solution |
|---------|----------------|----------|
| User IDs | `user-12345` | Remove label or use buckets |
| Request IDs | `req-abc-123` | Remove label |
| Timestamps | `2024-01-15T10:30:00Z` | Remove or bucket by hour |
| IP Addresses | `192.168.1.100` | Use CIDR blocks |
| Pod Names | `pod-abc-xyz-12345` | Use deployment name instead |
| URLs with params | `/api/users/12345` | Use route template |

## Files

| File | Description |
|------|-------------|
| `fetch_metrics.py` | Parser and tree builder |
| `index.html` | Three.js 3D visualization |
| `metrics_tree.json` | Generated data (output) |

## Requirements

- Python 3.7+
- `requests` library (only for URL fetching): `pip install requests`
- Modern web browser with WebGL

## How It Works

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│ /metrics        │────▶│ fetch_metrics│────▶│ metrics_tree.   │
│ endpoint        │     │ .py          │     │ json            │
└─────────────────┘     └──────────────┘     └────────┬────────┘
                                                      │
  Prometheus exposition format:                       ▼
  http_requests{method="GET"} 123         ┌─────────────────┐
  http_requests{method="POST"} 456        │ index.html      │
                                          │ (Three.js 3D)   │
                                          └─────────────────┘
```
