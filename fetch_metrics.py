#!/usr/bin/env python3
"""
Prometheus Metrics Cardinality Discovery Tool

Parses raw Prometheus exposition format from a /metrics endpoint
and builds a tree structure for visualization.

Each metric becomes a tree where:
- Root = metric name
- Children = label key/value pairs
- Leaf count = number of unique time series
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None  # Optional, only needed for URL fetching


def parse_prometheus_line(line: str) -> tuple[str, dict, float] | None:
    """
    Parse a single Prometheus metrics line.

    Returns (metric_name, labels_dict, value) or None if not a metric line.

    Examples:
        http_requests_total{method="GET",path="/api"} 1234
        node_cpu_seconds_total 5678.9
    """
    line = line.strip()

    # Skip empty lines and comments
    if not line or line.startswith('#'):
        return None

    # Regex to match metric with optional labels
    # metric_name{label1="value1",label2="value2"} value
    # or just: metric_name value

    # Pattern for metric with labels
    pattern_with_labels = r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\{([^}]*)\}\s+([^\s]+)$'
    # Pattern for metric without labels
    pattern_no_labels = r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\s+([^\s]+)$'

    match = re.match(pattern_with_labels, line)
    if match:
        metric_name = match.group(1)
        labels_str = match.group(2)
        value_str = match.group(3)

        # Parse labels
        labels = {}
        if labels_str:
            # Handle escaped quotes and commas in label values
            label_pattern = r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)?"'
            for label_match in re.finditer(label_pattern, labels_str):
                key = label_match.group(1)
                value = label_match.group(2) if label_match.group(2) else ""
                # Unescape escaped characters
                value = value.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')
                labels[key] = value

        try:
            value = float(value_str)
        except ValueError:
            value = 0.0

        return (metric_name, labels, value)

    match = re.match(pattern_no_labels, line)
    if match:
        metric_name = match.group(1)
        value_str = match.group(2)

        try:
            value = float(value_str)
        except ValueError:
            value = 0.0

        return (metric_name, {}, value)

    return None


def parse_prometheus_text(text: str) -> dict[str, list[dict]]:
    """
    Parse Prometheus exposition format text.

    Returns a dict mapping metric names to list of label dicts.
    """
    metrics = defaultdict(list)

    for line in text.split('\n'):
        parsed = parse_prometheus_line(line)
        if parsed:
            metric_name, labels, _ = parsed
            metrics[metric_name].append(labels)

    return dict(metrics)


def fetch_metrics_from_url(url: str, headers: dict = None, timeout: int = 30) -> str:
    """Fetch raw metrics text from a URL."""
    if requests is None:
        print("Error: 'requests' library required for URL fetching")
        print("Install with: pip install requests")
        sys.exit(1)

    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def load_metrics_from_file(filepath: str) -> str:
    """Load metrics text from a local file."""
    return Path(filepath).read_text()


def build_tree_for_metric(metric_name: str, series_list: list[dict]) -> dict:
    """
    Build a tree structure for a single metric.

    Returns a tree where each node has:
    - name: label key or "key=value" for identification
    - value: the label value (if applicable)
    - count: number of series passing through this node
    - children: list of child nodes
    """

    def insert_into_tree(tree: dict, labels: list[tuple[str, str]], depth: int = 0):
        """Recursively insert a series into the tree."""
        if depth >= len(labels):
            return

        key, value = labels[depth]
        node_id = f"{key}={value}"

        if "children" not in tree:
            tree["children"] = {}

        if node_id not in tree["children"]:
            tree["children"][node_id] = {
                "name": node_id,
                "key": key,
                "value": value,
                "count": 0,
                "children": {}
            }

        tree["children"][node_id]["count"] += 1
        insert_into_tree(tree["children"][node_id], labels, depth + 1)

    # Root node
    root = {
        "name": metric_name,
        "type": "metric",
        "count": len(series_list),
        "children": {}
    }

    for series in series_list:
        # Sort labels alphabetically for consistent tree structure
        labels = sorted(series.items())
        insert_into_tree(root, labels)

    # Convert children dicts to lists for JSON serialization
    def dict_children_to_list(node):
        if "children" in node and isinstance(node["children"], dict):
            node["children"] = list(node["children"].values())
            for child in node["children"]:
                dict_children_to_list(child)
        return node

    return dict_children_to_list(root)


def analyze_cardinality(tree: dict) -> dict:
    """Analyze a tree to find high-cardinality labels."""
    label_cardinality = defaultdict(set)

    def traverse(node, depth=0):
        if "key" in node:
            label_cardinality[node["key"]].add(node["value"])
        for child in node.get("children", []):
            traverse(child, depth + 1)

    traverse(tree)

    # Sort by cardinality descending
    sorted_labels = sorted(
        label_cardinality.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )

    return {
        "metric": tree["name"],
        "total_series": tree["count"],
        "label_cardinalities": {
            k: len(v) for k, v in sorted_labels
        },
        "high_cardinality_labels": [
            k for k, v in label_cardinality.items() if len(v) > 100
        ],
        "label_sample_values": {
            k: list(v)[:5] for k, v in sorted_labels[:10]  # Sample values for top 10 labels
        }
    }


def process_metrics(
    metrics_text: str,
    top_n: int = 50,
    min_series: int = 1
) -> dict:
    """
    Process raw Prometheus metrics text and build visualization data.
    """
    print("Parsing metrics...")
    metrics = parse_prometheus_text(metrics_text)

    print(f"Found {len(metrics)} unique metric names")

    # Sort by series count
    sorted_metrics = sorted(
        metrics.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )

    # Filter and limit
    filtered_metrics = [
        (name, series) for name, series in sorted_metrics
        if len(series) >= min_series
    ][:top_n]

    print(f"Processing top {len(filtered_metrics)} metrics...")

    trees = []
    analyses = []

    for i, (metric_name, series_list) in enumerate(filtered_metrics):
        print(f"  [{i+1}/{len(filtered_metrics)}] {metric_name}: {len(series_list)} series")

        tree = build_tree_for_metric(metric_name, series_list)
        trees.append(tree)

        analysis = analyze_cardinality(tree)
        analyses.append(analysis)

        if analysis["high_cardinality_labels"]:
            for label in analysis["high_cardinality_labels"]:
                count = analysis["label_cardinalities"][label]
                samples = analysis["label_sample_values"].get(label, [])[:3]
                print(f"      ⚠️  {label}: {count} unique values (e.g., {samples})")

    return {
        "trees": trees,
        "analyses": analyses,
        "metadata": {
            "total_metrics": len(metrics),
            "total_series": sum(len(s) for s in metrics.values()),
            "processed_metrics": len(filtered_metrics)
        }
    }


def generate_sample_data() -> dict:
    """Generate sample metrics in Prometheus format for testing."""
    import random

    lines = []

    # Sample metric 1: http_requests_total
    lines.append("# HELP http_requests_total Total HTTP requests")
    lines.append("# TYPE http_requests_total counter")

    regions = ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1"]
    services = ["api", "web", "worker", "scheduler"]
    methods = ["GET", "POST", "PUT", "DELETE"]
    endpoints = ["/api/users", "/api/orders", "/api/products", "/health", "/metrics"]
    pods = [f"pod-{svc}-{random.randint(1000,9999)}" for svc in services for _ in range(20)]

    for region in regions:
        for service in services:
            for method in methods:
                for endpoint in random.sample(endpoints, 3):
                    for pod in random.sample([p for p in pods if service in p], 8):
                        value = random.randint(100, 10000)
                        lines.append(
                            f'http_requests_total{{_label_0="{region}",_label_1="{service}",'
                            f'_label_2="{method}",_label_3="{endpoint}",_label_4="{pod}"}} {value}'
                        )

    # Sample metric 2: container_memory_usage_bytes
    lines.append("# HELP container_memory_usage_bytes Memory usage")
    lines.append("# TYPE container_memory_usage_bytes gauge")

    namespaces = ["default", "kube-system", "monitoring", "production"]
    containers = ["app", "sidecar", "proxy"]

    for ns in namespaces:
        for container in containers:
            for pod in random.sample(pods, 15):
                value = random.randint(1000000, 500000000)
                lines.append(
                    f'container_memory_usage_bytes{{_label_0="{ns}",_label_1="{container}",'
                    f'_label_2="{pod}"}} {value}'
                )

    # Sample metric 3: user_events_total (HIGH CARDINALITY - user IDs!)
    lines.append("# HELP user_events_total User events with problematic user_id label")
    lines.append("# TYPE user_events_total counter")

    user_ids = [f"user-{i:08d}" for i in range(500)]
    event_types = ["login", "logout", "purchase", "view", "click"]

    for user_id in user_ids:
        for event_type in random.sample(event_types, random.randint(1, 4)):
            region = random.choice(regions)
            value = random.randint(1, 100)
            lines.append(
                f'user_events_total{{_label_0="{event_type}",_label_1="{user_id}",'
                f'_label_2="{region}"}} {value}'
            )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Parse Prometheus /metrics endpoint and analyze cardinality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # From a /metrics endpoint
  python fetch_metrics.py --url http://localhost:8080/metrics

  # From a file
  python fetch_metrics.py --file ./metrics.txt

  # Generate and use sample data
  python fetch_metrics.py --sample

  # With authentication
  python fetch_metrics.py --url http://app:8080/metrics --bearer-token TOKEN
        """
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--url",
        help="URL of the /metrics endpoint to fetch"
    )
    source.add_argument(
        "--file", "-f",
        help="Local file containing Prometheus metrics"
    )
    source.add_argument(
        "--sample",
        action="store_true",
        help="Generate sample data for testing"
    )

    parser.add_argument(
        "--output", "-o",
        default="metrics_tree.json",
        help="Output JSON file (default: metrics_tree.json)"
    )
    parser.add_argument(
        "--top", "-n",
        type=int,
        default=50,
        help="Number of top metrics to process (default: 50)"
    )
    parser.add_argument(
        "--min-series",
        type=int,
        default=1,
        help="Minimum series count to include metric (default: 1)"
    )
    parser.add_argument(
        "--bearer-token",
        help="Bearer token for authentication"
    )
    parser.add_argument(
        "--basic-auth",
        help="Basic auth in format user:password"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Request timeout in seconds (default: 30)"
    )
    parser.add_argument(
        "--save-raw",
        help="Save raw metrics to this file (useful for debugging)"
    )

    args = parser.parse_args()

    # Build headers for auth
    headers = {}
    if args.bearer_token:
        headers["Authorization"] = f"Bearer {args.bearer_token}"
    if args.basic_auth:
        import base64
        encoded = base64.b64encode(args.basic_auth.encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"

    # Get metrics text
    if args.sample:
        print("Generating sample data...")
        metrics_text = generate_sample_data()
    elif args.file:
        print(f"Loading metrics from {args.file}...")
        metrics_text = load_metrics_from_file(args.file)
    else:
        print(f"Fetching metrics from {args.url}...")
        metrics_text = fetch_metrics_from_url(
            args.url,
            headers=headers if headers else None,
            timeout=args.timeout
        )

    # Optionally save raw metrics
    if args.save_raw:
        Path(args.save_raw).write_text(metrics_text)
        print(f"Raw metrics saved to {args.save_raw}")

    # Process
    result = process_metrics(
        metrics_text,
        top_n=args.top,
        min_series=args.min_series
    )

    # Add source info to metadata
    if args.url:
        result["metadata"]["source"] = args.url
    elif args.file:
        result["metadata"]["source"] = args.file
    else:
        result["metadata"]["source"] = "sample_data"

    # Write output
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n✅ Output written to {args.output}")
    print(f"   Total metrics found: {result['metadata']['total_metrics']}")
    print(f"   Total series: {result['metadata']['total_series']}")
    print(f"   Metrics processed: {result['metadata']['processed_metrics']}")
    print(f"\n   Open index.html to visualize")

    # Summary
    print("\n📊 Top Metrics by Cardinality:")
    for analysis in sorted(result["analyses"], key=lambda x: x["total_series"], reverse=True)[:10]:
        print(f"   {analysis['metric']}: {analysis['total_series']} series")
        if analysis["high_cardinality_labels"]:
            for label in analysis["high_cardinality_labels"][:3]:
                count = analysis["label_cardinalities"][label]
                samples = analysis.get("label_sample_values", {}).get(label, [])[:2]
                print(f"      ⚠️  {label}: {count} values (e.g., {samples})")


if __name__ == "__main__":
    main()
