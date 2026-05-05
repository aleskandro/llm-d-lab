#!/usr/bin/env python3
"""
Gateway API Inference Extension (k8s SIG) - EPP Flow Control Demo
=================================================================

This tool simulates multi-tenant LLM inference traffic to demonstrate the
Endpoint Picker (EPP) Flow Control layer. It visually proves how shifting
queues from the endpoints to the gateway proxy protects downstream VRAM
and ensures business-level QoS.

The playbook is designed to explicitly showcase:
  1. Priority-based QoS Differentiation: Strict ordering that prevents
     priority inversion (e.g., Batch traffic starving Premium chat).
  2. Intra-Priority Fairness: Equitable sharing of resources for flows
     at the exact same priority level under saturation.
  3. Backpressure & Saturation Management: Centralized EPP buffering
     that intentionally trades initial wait time (TTFT) to protect
     generation speed (TPOT) and enable Late Binding routing.

Prerequisites:
    Python 3.9+ (Zero external dependencies)

Usage:
    python3 demo.py --url http://localhost:8080/v1/completions
"""

import argparse
import concurrent.futures
import collections
import json
import random
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import csv


# ==============================================================================
# 1. CORE DATA MODELS (The Flexible Architecture)
# ==============================================================================

@dataclass
class Tenant:
    """
    Represents a discrete Flow within the EPP.
    The 'id' maps to the x-gateway-inference-fairness-id header.
    The 'priority' mimics the InferenceObjective strict ordering.
    """
    id: str
    model: str
    priority: int


@dataclass
class Stage:
    """Represents a phase in the demo narrative with specific QPS targets."""
    name: str
    duration_sec: int
    qps_targets: Dict[str, float]  # Maps Tenant.id -> Target Queries Per Second


# ==============================================================================
# 2. METRICS & THREAD-SAFE COLLECTOR
# ==============================================================================

class MetricsCollector:
    """
    Thread-safe metrics aggregator using sliding window deques.

    This real-time calculation is vital for observing the Flow Control layer's
    behavior: as the Saturation Detector allows the pool to recover, you will
    visually see the P90 TTFT metrics drain and return to healthy levels.
    """
    def __init__(self, window_size: int = 500):
        self.lock = threading.Lock()
        self.ttft_window = collections.defaultdict(lambda: collections.deque(maxlen=window_size))
        self.duration_window = collections.defaultdict(lambda: collections.deque(maxlen=window_size))
        self.completion_times = collections.defaultdict(lambda: collections.deque(maxlen=window_size))
        self.status_counts = collections.defaultdict(lambda: collections.defaultdict(int))
        self.active_requests = collections.defaultdict(int)

    def record_start(self, fairness_id: str) -> None:
        with self.lock:
            self.active_requests[fairness_id] += 1

    def record(self, fairness_id: str, status: str, ttft: Optional[float], duration: float) -> None:
        """Records a completed (or failed) request into the sliding window."""
        with self.lock:
            self.active_requests[fairness_id] -= 1
            if self.active_requests[fairness_id] < 0:
                self.active_requests[fairness_id] = 0
            self.status_counts[fairness_id][status] += 1
            if status == "200" and ttft is not None:
                now = time.monotonic()
                self.ttft_window[fairness_id].append((now, ttft))
                self.duration_window[fairness_id].append((now, duration))
                self.completion_times[fairness_id].append(now)

    def get_realtime_stats(self, tenant_id: str) -> Tuple[Optional[float], Optional[float], float, int, int, int, int, int]:
        """Calculates P90 latency and extracts status code counts for the UI."""
        with self.lock:
            now = time.monotonic()

            # Prune and calculate TTFT within physical 10s window (prevents falsely showing stale ultra-fast times when fully starved)
            recent_ttfts = sorted(val for ts, val in self.ttft_window[tenant_id] if now - ts <= 10.0)
            p90_ttft = recent_ttfts[int(len(recent_ttfts) * 0.9)] if recent_ttfts else None

            # Prune and calculate Duration similarly
            recent_durs = sorted(val for ts, val in self.duration_window[tenant_id] if now - ts <= 10.0)
            p90_dur = recent_durs[int(len(recent_durs) * 0.9)] if recent_durs else None

            stats = self.status_counts[tenant_id]
            s_200 = stats.get("200", 0)
            s_429 = sum(c for k, c in stats.items() if "429" in str(k))
            s_503 = sum(c for k, c in stats.items() if "503" in str(k))

            s_err = sum(c for k, c in stats.items() if "200" not in str(k) and "429" not in str(k) and "503" not in str(k))

            # Achieved QPS drops naturally if completions vanish in the last 10s.
            achieved_qps = 0.0
            recent_times = [ts for ts in self.completion_times[tenant_id] if now - ts <= 10.0]

            if len(recent_times) > 1:
                # Bounding division to prevent aggressive spikes.
                window_duration = max(now - recent_times[0], 0.1)
                achieved_qps = len(recent_times) / window_duration

            return p90_ttft, p90_dur, achieved_qps, s_200, s_429, s_503, s_err, self.active_requests[tenant_id]

# ==============================================================================
# 3. LOAD GENERATOR ENGINE
# ==============================================================================

class LoadGenerator:
    """
    Manages the open-loop HTTP sessions, dynamic payload math, and workers.
    """
    def __init__(self, args: argparse.Namespace, metrics: MetricsCollector, model_name: str):
        self.args = args
        self.metrics = metrics
        self.model_name = model_name
        # Pre-calculate token profiles to simulate unpredictable autoregressive workloads.
        self.prob_heavy = 0.3
        self.heavy_mult = 2.8
        self.avg_heavy_tokens = self.args.avg_prompt_tokens * self.heavy_mult
        self.avg_light_tokens = (self.args.avg_prompt_tokens - (self.prob_heavy * self.avg_heavy_tokens)) / (1.0 - self.prob_heavy)
        self.base_phrase = "Flow control demo payload."
        self.tokens_per_phrase = 5

    def verify_connectivity(self) -> None:
        """Fails fast if the target gateway is unreachable."""
        try:
            req = urllib.request.Request(
                self.args.url,
                data=json.dumps({"model": self.model_name, "prompt": ""}).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            urllib.request.urlopen(req, timeout=2.0)
        except urllib.error.URLError as e:
            if isinstance(e.reason, ConnectionRefusedError):
                print(f"\n[\033[1;31mFATAL\033[0m] Connection Refused to {self.args.url}! Is the EPP running?")
                sys.exit(1)
        except Exception:
            pass # 404/400 is fine, it means the gateway HTTP server is up.

    def _send_request(self, tenant: Tenant) -> None:
        """Constructs and executes a streaming LLM request, injecting FlowKeys."""
        # Math: Add +/- 20% jitter to prompt sizes.
        is_heavy = random.random() < self.prob_heavy
        target_tokens = self.avg_heavy_tokens if is_heavy else self.avg_light_tokens
        actual_prompt_tokens = int(target_tokens * random.uniform(0.8, 1.2))
        repetitions = max(1, actual_prompt_tokens // self.tokens_per_phrase)

        # Math: Add +/- 50% jitter to generation lengths.
        actual_max_tokens = max(1, int(self.args.avg_gen_tokens * random.uniform(0.5, 1.5)))

        payload = {
            "model": self.model_name,
            "prompt": " ".join([self.base_phrase] * repetitions),
            "max_tokens": actual_max_tokens,
            "stream": True
        }

        # Apply the FlowKey. Objective maps to the InferenceObjective CRD name.
        headers = {
            'Content-Type': 'application/json',
            'x-gateway-inference-fairness-id': tenant.id,
            'x-gateway-inference-objective': tenant.model,
        }

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(self.args.url, data=data, headers=headers, method='POST')

        start_time = time.monotonic()
        ttft = None
        status_str = "Unknown"

        self.metrics.record_start(tenant.id)

        try:
            with urllib.request.urlopen(req, timeout=90.0) as response:
                status_code = response.getcode()
                if status_code == 200:
                    status_str = "200"
                    while True:
                        line = response.readline()
                        if not line:
                            break
                        if ttft is None:
                            # Capture TTFT strictly on the arrival of the first newline boundary.
                            ttft = time.monotonic() - start_time
                else:
                    msg = response.read().decode('utf-8', errors='ignore').lower()
                    if status_code == 503 or "timed out" in msg: status_str = "503 (TTL Evict)"
                    elif status_code == 429 or "rejected" in msg: status_str = "429 (Capacity Rej)"
                    else: status_str = f"{status_code}"

        except urllib.error.HTTPError as e:
            status_code = e.code
            msg = e.read().decode('utf-8', errors='ignore').lower()
            if status_code == 503 or "timed out" in msg: status_str = "503 (TTL Evict)"
            elif status_code == 429 or "rejected" in msg: status_str = "429 (Capacity Rej)"
            else: status_str = f"{status_code}"
        except urllib.error.URLError as e:
            if isinstance(e.reason, (TimeoutError, socket.timeout)):
                status_str = "Timeout (Read)"
            elif isinstance(e.reason, ConnectionRefusedError):
                status_str = "Error (Conn Refused)"
            else:
                status_str = f"Error ({type(e.reason).__name__})"
        except (TimeoutError, socket.timeout):
            status_str = "Timeout (Read)"
        except Exception as e:
            status_str = f"Error ({type(e).__name__})"

        duration = time.monotonic() - start_time
        self.metrics.record(tenant.id, status_str, ttft, duration)

    def run_tenant_worker(self, tenant: Tenant, executor: concurrent.futures.ThreadPoolExecutor, stages: List[Stage], stop_event: threading.Event) -> None:
        """
        Background thread orchestrator for a specific flow.
        Uses exponential distribution to simulate organic, open-loop arrival rates.
        """
        start_time = time.monotonic()
        total_duration = sum(s.duration_sec for s in stages)
        end_time = start_time + total_duration
        next_req_time = start_time

        while time.monotonic() < end_time and not stop_event.is_set():
            now = time.monotonic()
            elapsed = now - start_time

            # Determine the current stage based on elapsed time.
            accumulated = 0.0
            current_stage = stages[-1]
            for stage in stages:
                accumulated += stage.duration_sec
                if elapsed < accumulated:
                    current_stage = stage
                    break

            current_qps = current_stage.qps_targets.get(tenant.id, 0.0)

            # If this flow is paused in this stage, sleep briefly and evaluate again.
            if current_qps <= 0:
                if stop_event.wait(0.1):
                    break
                next_req_time = time.monotonic()
                continue

            # Open-loop load generation via Poisson process
            delay = random.expovariate(current_qps)
            next_req_time += delay

            sleep_duration = next_req_time - time.monotonic()
            if sleep_duration > 0:
                if stop_event.wait(sleep_duration):
                    break
            else:
                # We fell behind (due to CPU or extreme load); reset so we don't violently burst to catch up.
                next_req_time = time.monotonic()

            if not stop_event.is_set():
                executor.submit(self._send_request, tenant)


# ==============================================================================
# 4. PLAYBOOK CONFIGURATION (The Narrative)
# ==============================================================================

def build_playbook(args: argparse.Namespace, capacity_qps: float) -> Tuple[List[Tenant], List[Stage]]:
    """
    Defines the actors (Flows) and the narrative timeline (Stages).
    """
    tenants =[
        Tenant("premium-A", "premium", 1),
        Tenant("standard-A", "standard", 0),
        Tenant("standard-B", "standard", 0),
        Tenant("batch-A", "batch", -1),
    ]

    burst_qps = capacity_qps * args.burst_multiplier

    stages =[
        Stage("1. Steady State (Healthy Buffer)", 30, {
            "premium-A": capacity_qps * 0.15,
            "standard-A": capacity_qps * 0.35,
        }),
        Stage("2. Saturation & Strict Priority (Batch Spikes)", 40, {
            "premium-A": capacity_qps * 0.15,
            "standard-A": capacity_qps * 0.35,
            "batch-A": burst_qps * 0.8, # Spike massive low-priority traffic.
        }),
        Stage("3. Intra-Priority Fairness (Standard Tier Clash)", 60, {
            "premium-A": capacity_qps * 0.15, # Premium should remain pristine.
            "standard-A": burst_qps * 0.5,    # Two identical priority flows
            "standard-B": burst_qps * 0.5,    # battle for remaining capacity.
        }),
        Stage("4. Recovery (Queues Drain)", 30, {
            "premium-A": capacity_qps * 0.15,
            "standard-A": capacity_qps * 0.10,
        })
    ]

    # Scale the overall demo time up or down via CLI arguments.
    for s in stages:
        s.duration_sec = int(s.duration_sec * args.time_factor)

    return tenants, stages


# ==============================================================================
# 5. CLI DASHBOARD & ENTRYPOINT
# ==============================================================================

def draw_dashboard(is_first_render: bool, elapsed: float, total: float, stage: Stage, tenants: List[Tenant], metrics: MetricsCollector, capacity: float) -> None:
    """Renders the real-time terminal UI."""
    active_qps = sum(stage.qps_targets.values())
    bp_status = "\033[1;31mSATURATED\033[0m" if active_qps > capacity else "\033[1;32mHEALTHY\033[0m"

    # Reposition terminal cursor exactly to the top of the dashboard
    num_lines = len(tenants) + 6
    if not is_first_render:
        sys.stdout.write(f"\033[{num_lines}A")

    # Buffer lines to prevent terminal flicker
    out = []
    out.append(f"\033[K\033[1;36m[{int(elapsed):03d}s / {int(total):03d}s] {stage.name}\033[0m")
    out.append(f"\033[KSaturation State: {bp_status} | Target Global Load: {active_qps:.1f} QPS (Capacity: ~{capacity:.1f})")
    out.append("\033[K" + "-" * 119)
    out.append(f"\033[K{'FLOW (FAIRNESS ID)':<20} | {'PRI':<3} | {'TARGET QPS':<10} | {'ACHIEVED':<10} | {'CONCURR':<7} | {'P90 TTFT':<10} | {'P90 TOTAL':<10} | {'200s':<5} | {'429s':<5} | {'503s':<5} | {'ERRs':<5}")
    out.append("\033[K" + "-" * 119)

    for t in sorted(tenants, key=lambda x: x.priority, reverse=True):
        t_qps = stage.qps_targets.get(t.id, 0.0)
        p90_ttft, p90_dur, achieved_qps, s_200, s_429, s_503, s_err, active_concurr = metrics.get_realtime_stats(t.id)

        # Color code TTFT based on latency to highlight queueing visually
        if p90_ttft is not None:
            # Under flow control, TTFT acts as our queue indicator.
            ttft_color = "\033[1;32m" if p90_ttft < 2.0 else "\033[1;33m" if p90_ttft < 10.0 else "\033[1;31m"
            ttft_str = f"{ttft_color}{p90_ttft:<9.2f}s\033[0m"
        else:
            ttft_str = "  -       "

        dur_str = f"{p90_dur:<9.2f}s" if p90_dur is not None else "  -       "

        out.append(f"\033[K{t.id:<20} | {t.priority:<3} | {t_qps:<10.1f} | {achieved_qps:<10.1f} | {active_concurr:<7} | {ttft_str} | {dur_str} | {s_200:<5} | {s_429:<5} | {s_503:<5} | {s_err:<5}")

    out.append("\033[K" + "-" * 119)

    # Render entire buffer at once.
    sys.stdout.write("\n".join(out) + "\n")
    sys.stdout.flush()


def get_current_metrics_dict(tt: float, stage: Stage, tenants: List[Tenant], metrics: MetricsCollector):
    csv = []
    for t in sorted(tenants, key=lambda x: x.priority, reverse=True):
        t_qps = stage.qps_targets.get(t.id, 0.0)
        p90_ttft, p90_dur, achieved_qps, s_200, s_429, s_503, s_err, active_concurr = metrics.get_realtime_stats(t.id)
        csv.append({
            "t": tt,
            "tenant": t.id,
            "target_qps": t_qps,
            "p90_ttft": p90_ttft,
            "p90_dur": p90_dur,
            "achieved_qps": achieved_qps,
            "s_200": s_200,
            "s_429": s_429,
            "s_503": s_503,
            "s_err": s_err,
            "active_concurrency": active_concurr,
        })
    return csv

def main():
    if sys.version_info < (3, 9):
        print("[\033[1;31mFATAL\033[0m] Python 3.9+ is required for cancel_futures functionality.")
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Gateway API Inference Extension EPP - Flow Control Demo",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    gateway_group = parser.add_argument_group("Gateway Configuration")
    gateway_group.add_argument("--url", default="http://localhost:8080/v1/completions", help="EPP proxy endpoint.")
    gateway_group.add_argument("--model", default="Qwen/Qwen3-32B", help="Model name as registered in vLLM (--served-model-name).")
    gateway_group.add_argument("--max-workers", type=int, default=1500, help="Max concurrent HTTP connections (bounding proxy memory).")

    demo_group = parser.add_argument_group("Demo & Playbook Overrides")
    demo_group.add_argument("--time-factor", type=float, default=1.0, help="Multiplier to scale the duration of the demo up or down.")
    demo_group.add_argument("--burst-multiplier", type=float, default=2.0, help="How violently batch/clashing workloads burst relative to capacity.")
    demo_group.add_argument("--sim-replicas", type=int, default=3, help="Number of vLLM replicas for capacity calibration.")
    demo_group.add_argument("--sim-max-seqs", type=int, default=10, help="vLLM max_num_seqs per replica for capacity calibration.")

    payload_group = parser.add_argument_group("Payload Math")
    payload_group.add_argument("--avg-prompt-tokens", type=int, default=150, help="Average input tokens.")
    payload_group.add_argument("--avg-gen-tokens", type=int, default=100, help="Average output tokens.")

    args = parser.parse_args()

    # Calculate target Little's Law baseline (L = λW).
    sim_replicas, sim_max_seqs = args.sim_replicas, args.sim_max_seqs
    est_prefill_ms = 50 + (args.avg_prompt_tokens * 2)
    est_decode_ms = args.avg_gen_tokens * 20
    base_duration_sec = (est_prefill_ms + est_decode_ms) / 1000.0
    capacity_qps = (sim_replicas * sim_max_seqs) / base_duration_sec

    metrics = MetricsCollector(window_size=100)
    generator = LoadGenerator(args, metrics, args.model)
    generator.verify_connectivity()

    tenants, stages = build_playbook(args, capacity_qps)
    total_duration = sum(s.duration_sec for s in stages)

    print("\033[2J\033[H", end="")
    print("┌─────────────────────────────────────────────────────────────┐")
    print("│ EPP Flow Control Layer: Multi-Tenancy & QoS Simulator       │")
    print("└─────────────────────────────────────────────────────────────┘")
    print(f"Auto-Calibrated Target Capacity: ~{capacity_qps:.1f} QPS\n")

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers)
    threads = []

    try:
        stop_event = threading.Event()

        # 1. Start background flow generators.
        for tenant in tenants:
            t = threading.Thread(target=generator.run_tenant_worker, args=(tenant, executor, stages, stop_event))
            t.daemon = True
            t.start()
            threads.append(t)

        start_time = time.monotonic()
        is_first_render = True
        metrics_store = []
        # 2. Main UI update loop.
        t = 0
        while True:
            elapsed = time.monotonic() - start_time
            total_active = sum(metrics.get_realtime_stats(t.id)[7] for t in tenants)

            if elapsed >= total_duration:
                # Narratives are done, signal workers to immediately stop injecting traffic.
                stop_event.set()
                current_stage = Stage(f"5. Terminated (Draining - {int(elapsed - total_duration)}s)", 12, {})

                if total_active == 0 and elapsed >= total_duration + 12.0:
                    break
                elif elapsed >= total_duration + 95.0:
                    break

            else:
                current_stage = stages[-1]
                accum = 0
                for s in stages:
                    accum += s.duration_sec
                    if elapsed < accum:
                        current_stage = s
                        break

            draw_dashboard(is_first_render, elapsed, total_duration + 12.0, current_stage, tenants, metrics, capacity_qps)
            metrics_store += get_current_metrics_dict(t, current_stage, tenants, metrics)
            is_first_render = False
            t += 0.5
            time.sleep(0.5)

        # 3. Graceful Exit
        print("\n\nTest narrative complete. Awaiting socket terminations for any straggling requests...")

        # Cancel unstarted futures so we don't process the backlog queue endlessly.
        executor.shutdown(wait=True, cancel_futures=True)

        print("\n\nStoring metrics as csv")
        with open('flow_control_metrics.csv', 'w', newline='') as csvfile:
            fieldnames = list(metrics_store[0].keys())
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(metrics_store)

    except KeyboardInterrupt:
        stop_event.set()
        print("\n\n[\033[1;33mABORT\033[0m] Caught Ctrl+C. Force stopping workers...")
        executor.shutdown(wait=False, cancel_futures=True)

if __name__ == "__main__":
    main()