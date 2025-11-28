#!/usr/bin/env python3
"""
Prometheus/Thanos High Cardinality Metrics Discovery Tool

Fetches metrics data and builds a tree structure for visualization.
Each metric becomes a tree where:
- Root = metric name
- Children = label key/value pairs
- Leaf count = number of unique time series
"""

import argparse
import json
import sys
from collections import defaultdict
from typing import Any
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    print("Please install requests: pip install requests")
    sys.exit(1)


def fetch_tsdb_status(base_url: str, headers: dict = None) -> dict:
    """Fetch TSDB status for quick cardinality overview."""
    url = urljoin(base_url, "/api/v1/status/tsdb")
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]


def fetch_metric_names(base_url: str, headers: dict = None) -> list[str]:
    """Fetch all metric names."""
    url = urljoin(base_url, "/api/v1/label/__name__/values")
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]


def fetch_series_for_metric(
    base_url: str,
    metric_name: str,
    headers: dict = None,
    limit: int = 10000
) -> list[dict]:
    """Fetch all series for a specific metric."""
    url = urljoin(base_url, "/api/v1/series")
    params = {
        "match[]": f'{metric_name}{{}}',
    }
    resp = requests.get(url, params=params, headers=headers, timeout=60)
    resp.raise_for_status()
    series = resp.json()["data"]
    return series[:limit]  # Limit to prevent memory issues


def build_tree_for_metric(metric_name: str, series_list: list[dict]) -> dict:
    """
    Build a tree structure for a single metric.

    Returns a tree where each node has:
    - name: label key or "key=value" for leaf identification
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
        # Extract labels, excluding __name__
        labels = sorted([
            (k, v) for k, v in series.items()
            if k != "__name__"
        ])
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

    return {
        "metric": tree["name"],
        "total_series": tree["count"],
        "label_cardinalities": {
            k: len(v) for k, v in label_cardinality.items()
        },
        "high_cardinality_labels": [
            k for k, v in label_cardinality.items() if len(v) > 100
        ]
    }


def fetch_and_build_trees(
    base_url: str,
    headers: dict = None,
    top_n: int = 20,
    series_limit: int = 5000
) -> dict:
    """
    Fetch top N metrics by cardinality and build trees for each.
    """
    print(f"Fetching TSDB status from {base_url}...")

    try:
        tsdb_status = fetch_tsdb_status(base_url, headers)
        # Get top metrics by series count
        top_metrics = [
            item["name"]
            for item in tsdb_status.get("seriesCountByMetricName", [])[:top_n]
        ]
        print(f"Found {len(top_metrics)} top metrics by cardinality")
    except Exception as e:
        print(f"Could not fetch TSDB status: {e}")
        print("Falling back to fetching all metric names...")
        all_metrics = fetch_metric_names(base_url, headers)
        top_metrics = all_metrics[:top_n]

    trees = []
    analyses = []

    for i, metric_name in enumerate(top_metrics):
        print(f"[{i+1}/{len(top_metrics)}] Fetching series for {metric_name}...")
        try:
            series = fetch_series_for_metric(
                base_url, metric_name, headers, limit=series_limit
            )
            print(f"  Found {len(series)} series")

            tree = build_tree_for_metric(metric_name, series)
            trees.append(tree)

            analysis = analyze_cardinality(tree)
            analyses.append(analysis)

            if analysis["high_cardinality_labels"]:
                print(f"  ⚠️  High cardinality labels: {analysis['high_cardinality_labels']}")

        except Exception as e:
            print(f"  Error: {e}")

    return {
        "trees": trees,
        "analyses": analyses,
        "metadata": {
            "source": base_url,
            "top_n": top_n,
            "series_limit": series_limit
        }
    }


def generate_sample_data() -> dict:
    """Generate sample data for testing without a live Prometheus."""
    import random

    sample_trees = []

    # Sample metric 1: http_requests_total with high cardinality
    regions = ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1"]
    services = ["api", "web", "worker", "scheduler"]
    methods = ["GET", "POST", "PUT", "DELETE"]
    # High cardinality: many endpoints and pod names
    endpoints = [f"/api/v{v}/{resource}" for v in range(1, 3) for resource in ["users", "orders", "products", "inventory", "payments", "notifications"]]
    pod_names = [f"pod-{svc}-{hash}" for svc in services for hash in [f"{random.randint(1000,9999)}" for _ in range(25)]]

    http_series = []
    for region in regions:
        for service in services:
            for method in methods:
                for endpoint in random.sample(endpoints, min(5, len(endpoints))):
                    for pod in random.sample([p for p in pod_names if service in p], min(10, 25)):
                        http_series.append({
                            "__name__": "http_requests_total",
                            "_label_0": region,
                            "_label_1": service,
                            "_label_2": method,
                            "_label_3": endpoint,
                            "_label_4": pod
                        })

    # Sample metric 2: container_memory_usage with moderate cardinality
    namespaces = ["default", "kube-system", "monitoring", "production", "staging"]
    container_names = ["app", "sidecar", "init", "proxy"]

    memory_series = []
    for ns in namespaces:
        for container in container_names:
            for pod in random.sample(pod_names, min(15, len(pod_names))):
                memory_series.append({
                    "__name__": "container_memory_usage_bytes",
                    "_label_0": ns,
                    "_label_1": container,
                    "_label_2": pod
                })

    # Sample metric 3: custom_user_events with VERY high cardinality (user IDs)
    user_ids = [f"user-{i:08d}" for i in range(500)]
    event_types = ["login", "logout", "purchase", "view", "click"]

    user_series = []
    for user_id in user_ids:
        for event_type in random.sample(event_types, random.randint(1, 5)):
            user_series.append({
                "__name__": "custom_user_events_total",
                "_label_0": event_type,
                "_label_1": user_id,  # This is the problematic high-cardinality label
                "_label_2": random.choice(regions)
            })

    # Build trees
    for metric_name, series_list in [
        ("http_requests_total", http_series),
        ("container_memory_usage_bytes", memory_series),
        ("custom_user_events_total", user_series)
    ]:
        tree = build_tree_for_metric(metric_name, series_list)
        sample_trees.append(tree)

    return {
        "trees": sample_trees,
        "analyses": [analyze_cardinality(t) for t in sample_trees],
        "metadata": {
            "source": "sample_data",
            "note": "Generated sample data for visualization testing"
        }
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Prometheus metrics and build cardinality trees"
    )
    parser.add_argument(
        "--url",
        default="http://localhost:9090",
        help="Prometheus/Thanos base URL"
    )
    parser.add_argument(
        "--output", "-o",
        default="metrics_tree.json",
        help="Output JSON file"
    )
    parser.add_argument(
        "--top", "-n",
        type=int,
        default=20,
        help="Number of top metrics to analyze"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=5000,
        help="Max series per metric"
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Generate sample data instead of querying Prometheus"
    )
    parser.add_argument(
        "--bearer-token",
        help="Bearer token for authentication"
    )
    parser.add_argument(
        "--basic-auth",
        help="Basic auth in format user:password"
    )

    args = parser.parse_args()

    headers = {}
    if args.bearer_token:
        headers["Authorization"] = f"Bearer {args.bearer_token}"
    if args.basic_auth:
        import base64
        encoded = base64.b64encode(args.basic_auth.encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"

    if args.sample:
        print("Generating sample data...")
        result = generate_sample_data()
    else:
        result = fetch_and_build_trees(
            args.url,
            headers=headers if headers else None,
            top_n=args.top,
            series_limit=args.limit
        )

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n✅ Output written to {args.output}")
    print(f"   Total metrics: {len(result['trees'])}")
    print(f"   Open index.html to visualize")

    # Print summary
    print("\n📊 Cardinality Summary:")
    for analysis in sorted(result["analyses"], key=lambda x: x["total_series"], reverse=True):
        print(f"   {analysis['metric']}: {analysis['total_series']} series")
        if analysis["high_cardinality_labels"]:
            for label in analysis["high_cardinality_labels"]:
                count = analysis["label_cardinalities"][label]
                print(f"      ⚠️  {label}: {count} unique values")


if __name__ == "__main__":
    main()
