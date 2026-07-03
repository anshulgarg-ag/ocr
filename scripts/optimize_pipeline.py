#!/usr/bin/env python3
"""
OCR Pipeline optimization wrapper.
Combines RTK (CLI filtering) + Headroom (memory optimization) for debugging.
"""

import subprocess
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from headroom_compress import HeadroomMemory, OCRPipelineOptimization, OptimizationStats


class PipelineOptimizer:
    """Optimize OCR pipeline debugging and monitoring."""

    def __init__(self, rtk_exe: str = "rtk.exe"):
        self.rtk = rtk_exe

    def docker_status(self) -> str:
        """Get optimized Docker status."""
        result = subprocess.run(
            [self.rtk, "docker", "ps"],
            capture_output=True,
            text=True,
        )
        return result.stdout

    def service_logs(self, service: str, lines: int = 50) -> str:
        """Get optimized service logs."""
        cmd = ["docker", "logs", service, "--tail", str(lines)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        # Pipe through RTK for additional filtering
        rtk_result = subprocess.run(
            [self.rtk, "log"],
            input=result.stdout,
            capture_output=True,
            text=True,
        )
        return rtk_result.stdout

    def prefect_status(self) -> str:
        """Get optimized Prefect flow status."""
        result = subprocess.run(
            [self.rtk, "prefect", "flow-run", "ls"],
            capture_output=True,
            text=True,
        )
        return result.stdout

    def health_check(self) -> dict:
        """Check all OCR pipeline services health."""
        services = {
            "qdrant": "http://localhost:6333/health",
            "neo4j": "http://localhost:7474/db/neo4j/exec",
            "chandra_ocr": "http://localhost:8001/health",
            "embeddings": "http://localhost:8002/health",
            "graph_server": "http://localhost:8003/health",
        }

        status = {}
        for service, url in services.items():
            try:
                result = subprocess.run(
                    ["curl", "-sf", url],
                    capture_output=True,
                    timeout=2,
                )
                status[service] = (
                    "healthy" if result.returncode == 0 else "unhealthy"
                )
            except Exception as e:
                status[service] = f"error: {e}"

        return status

    def save_debug_context(self, issue: str, context: dict):
        """Save debug context for memory optimization."""
        HeadroomMemory.add(
            "debug_issue",
            json.dumps(context, separators=(",", ":")),
            label=issue,
        )
        print(f"Saved debug context for '{issue}'")

    def show_stats(self):
        """Show optimization statistics."""
        print("RTK Savings:")
        print(
            subprocess.run([self.rtk, "gain"], capture_output=True, text=True).stdout
        )
        print("\nHeadroom Savings:")
        print(OptimizationStats.show_savings())


def main():
    """Example usage of pipeline optimizer."""
    optimizer = PipelineOptimizer()

    print("=== OCR Pipeline Status ===\n")

    # Check service health
    print("Service Health:")
    health = optimizer.health_check()
    for service, status in health.items():
        symbol = "✓" if status == "healthy" else "✗"
        print(f"  {symbol} {service}: {status}")

    print("\n=== Docker Services ===")
    print(optimizer.docker_status())

    print("\n=== Token Optimization Stats ===")
    optimizer.show_stats()


if __name__ == "__main__":
    main()
