import json
import optparse
import os
import sys
import matplotlib.pyplot as plt
from datetime import datetime

def load_prom_data(filepath, filter_func=None):
    if not os.path.exists(filepath):
        return {}
    with open(filepath) as f:
        data = json.load(f)
    
    if data.get('status') != 'success':
        return {}
        
    results = {}
    for result in data.get('data', {}).get('result', []):
        metric = result.get('metric', {})
        if filter_func and not filter_func(metric):
            continue
            
        for ts, val in result.get('values', []):
            results[ts] = results.get(ts, 0.0) + float(val)
            
    return results

def main():
    if len(sys.argv) < 2:
        print("Usage: python plot_results.py <result_dir>")
        sys.exit(1)
        
    result_dir = sys.argv[1]
    
    # Load 2xx and 4xx rate for /products
    rps_2xx = load_prom_data(f"{result_dir}/prom_http_requests_rate.json", lambda m: m.get("handler") == "/products" and m.get("status") == "2xx")
    rps_4xx = load_prom_data(f"{result_dir}/prom_http_requests_rate.json", lambda m: m.get("handler") == "/products" and m.get("status") == "4xx")
    
    # Load CPU usage
    cpu_usage = load_prom_data(f"{result_dir}/prom_cpu_usage.json")
    
    # Get common timestamps (sorted)
    all_ts = sorted(list(set(list(rps_2xx.keys()) + list(rps_4xx.keys()) + list(cpu_usage.keys()))))
    if not all_ts:
        print("No valid data found to plot.")
        sys.exit(0)
    
    start_ts = all_ts[0]
    x_axis = [ts - start_ts for ts in all_ts]
    
    y_2xx = [rps_2xx.get(ts, 0.0) for ts in all_ts]
    y_4xx = [rps_4xx.get(ts, 0.0) for ts in all_ts]
    y_cpu = [cpu_usage.get(ts, 0.0) for ts in all_ts]
    
    fig, ax1 = plt.subplots(figsize=(10, 6))

    color = 'tab:blue'
    ax1.set_xlabel('Time (seconds)')
    ax1.set_ylabel('Requests per Second (RPS)', color=color)
    ax1.plot(x_axis, y_2xx, color=color, label='2xx Success', linewidth=2)
    if any(y_4xx):
        ax1.plot(x_axis, y_4xx, color='tab:red', label='4xx Errors', linewidth=2)
    ax1.tick_params(axis='y', labelcolor=color)
    
    # 0 RPS to max(max(2xx)+20, 200)
    ax1.set_ylim(bottom=0, top=max(100, max(y_2xx + [0]) * 1.2))

    ax2 = ax1.twinx()
    color = 'tab:orange'
    ax2.set_ylabel('CPU Usage (Cores)', color=color)
    ax2.plot(x_axis, y_cpu, color=color, label='CPU Usage', linestyle='--', linewidth=2)
    ax2.tick_params(axis='y', labelcolor=color)
    ax2.set_ylim(bottom=0, top=max(0.2, max(y_cpu + [0]) * 1.5))

    fig.tight_layout()
    plt.title(f"Experiment Results: {os.path.basename(os.path.abspath(result_dir))}")
    
    # Combine legends
    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper left')
    
    output_path = os.path.join(result_dir, "dashboard.png")
    plt.savefig(output_path, dpi=150)
    print(f"Graph saved to {output_path}")

if __name__ == "__main__":
    main()
