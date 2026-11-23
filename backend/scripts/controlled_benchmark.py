import asyncio
import statistics
import time
from httpx import AsyncClient, ASGITransport
from app.main import app


async def benchmark_health_and_ready():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Scenario A: 50 concurrent requests to /health
        t0 = time.perf_counter()
        tasks = [client.get("/health") for _ in range(50)]
        results = await asyncio.gather(*tasks)
        durations = [(time.perf_counter() - t0) * 1000] # total
        assert all(r.status_code == 200 for r in results)
        health_total_ms = (time.perf_counter() - t0) * 1000

        # Scenario B: 50 concurrent requests to /ready
        t0 = time.perf_counter()
        tasks = [client.get("/ready") for _ in range(50)]
        results = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in results)
        ready_total_ms = (time.perf_counter() - t0) * 1000

        return {
            "health_50_reqs_total_ms": round(health_total_ms, 2),
            "health_req_avg_ms": round(health_total_ms / 50, 2),
            "ready_50_reqs_total_ms": round(ready_total_ms, 2),
            "ready_req_avg_ms": round(ready_total_ms / 50, 2),
        }


async def benchmark_blueprint_coalescing():
    transport = ASGITransport(app=app)
    payload = {
        "building_typology": "residential_single",
        "floors": 1,
        "built_up_area_sqft": 2000.0,
        "quality_grade": "standard",
        "ground_coverage_ratio": 0.6,
        "plot_width_m": 12.0,
        "plot_depth_m": 15.0,
        "required_rooms": ["Living Room", "Kitchen", "Master Bedroom"],
        "ai_provider": "mock",
        "bypass_cache": False,
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First: 3 SIMULTANEOUS identical requests to test in-flight coalescing
        t0 = time.perf_counter()
        tasks = [
            client.post("/api/generate-floorplan", json=payload)
            for _ in range(3)
        ]
        responses = await asyncio.gather(*tasks)
        simultaneous_ms = (time.perf_counter() - t0) * 1000
        assert all(r.status_code == 200 for r in responses)

        # Second: Immediate repeat request to test cache hit
        t0 = time.perf_counter()
        cached_resp = await client.post("/api/generate-floorplan", json=payload)
        cache_hit_ms = (time.perf_counter() - t0) * 1000
        assert cached_resp.status_code == 200

        return {
            "3_simultaneous_identical_ms": round(simultaneous_ms, 2),
            "single_cache_hit_ms": round(cache_hit_ms, 2),
        }


async def main():
    print("--- RUNNING CONTROLLED BENCHMARKS ---")
    health_results = await benchmark_health_and_ready()
    print("Health & Readiness Benchmarks:", health_results)

    blueprint_results = await benchmark_blueprint_coalescing()
    print("Blueprint Coalescing & Caching Benchmarks:", blueprint_results)


if __name__ == "__main__":
    asyncio.run(main())
