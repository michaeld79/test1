# Prometheus Cardinality Explorer

A 3D visualization tool for discovering high cardinality metrics in Prometheus/Thanos.

## The Problem

High cardinality metrics can cause:
- Memory issues in Prometheus/Thanos
- Slow queries
- Increased storage costs

Finding the source is hard when label names are generic (like `_label_0`, `_label_1`).

## The Solution

This tool builds a **tree visualization** where:
- **Root** = metric name
- **Children** = label key/value pairs
- **Node size** = number of series passing through
- **Node color** = cardinality level (green/yellow/red)

You can visually see where cardinality "explodes" and identify problematic labels by their actual values.

## Quick Start

### Option 1: Use Sample Data

```bash
# Generate sample data
python3 fetch_metrics.py --sample

# Start a local server
python3 -m http.server 8080

# Open http://localhost:8080 in your browser
```

### Option 2: Query Your Prometheus

```bash
# Fetch real data from Prometheus
python3 fetch_metrics.py --url http://your-prometheus:9090

# With authentication
python3 fetch_metrics.py --url http://prometheus:9090 --bearer-token YOUR_TOKEN

# Start visualization
python3 -m http.server 8080
```

## Usage

### Python Script Options

```
python3 fetch_metrics.py [OPTIONS]

Options:
  --url URL            Prometheus/Thanos base URL (default: http://localhost:9090)
  --output, -o FILE    Output JSON file (default: metrics_tree.json)
  --top, -n N          Number of top metrics to analyze (default: 20)
  --limit, -l N        Max series per metric (default: 5000)
  --sample             Generate sample data instead of querying
  --bearer-token TOKEN Bearer token for authentication
  --basic-auth USER:PASS Basic auth credentials
```

### Visualization Controls

| Control | Action |
|---------|--------|
| **Click** | Select a node |
| **Scroll** | Zoom in/out |
| **Drag** | Rotate view |
| **R** | Reset camera |
| **Search** | Filter nodes by label value |

## Understanding the Visualization

### Node Colors
- 🟢 **Green**: Low cardinality (<100 series)
- 🟡 **Yellow**: Medium cardinality (100-1000 series)
- 🔴 **Red**: High cardinality (>1000 series)

### Tree Structure

```
http_requests_total (root) → 50K series
├── _label_0="us-east-1" → 12K series
│   ├── _label_1="api" → 3K series
│   │   └── _label_2="user-12345" → 100 series  ← PROBLEM: user IDs!
│   └── _label_1="web" → 2K series
└── _label_0="eu-west-1" → 15K series
```

When you see a branch suddenly explode with many children, that's your high cardinality culprit.

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

- `fetch_metrics.py` - Python script to fetch and process metrics
- `index.html` - Three.js visualization
- `metrics_tree.json` - Generated data file (output)

## Requirements

- Python 3.7+
- `requests` library (`pip install requests`)
- Modern web browser with WebGL support

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│ Prometheus/     │────▶│ fetch_metrics│────▶│ metrics_tree.   │
│ Thanos          │     │ .py          │     │ json            │
└─────────────────┘     └──────────────┘     └────────┬────────┘
                                                      │
                                                      ▼
                                             ┌─────────────────┐
                                             │ index.html      │
                                             │ (Three.js)      │
                                             └─────────────────┘
```
