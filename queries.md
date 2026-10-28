# Queries for the Java heap lab

Prometheus is the source of history. These queries read its disk, so they still return data after the Java pod is gone.

Open the UI:

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090
```

Then browse to http://localhost:9090/graph and set the range to the last hour.

## While the app is running

Latest heap used, in bytes. No time range, so this is only the newest sample:

```promql
jvm_memory_used_bytes{job="java-app", area="heap"}
```

Same value in mebibytes:

```promql
jvm_memory_used_bytes{job="java-app", area="heap"} / 1024 / 1024
```

Heap ceiling from `-Xmx256m`. This stays flat:

```promql
jvm_memory_max_bytes{job="java-app", area="heap"} / 1024 / 1024
```

Fill ratio. `1` means the heap is at its ceiling:

```promql
jvm_memory_used_bytes{job="java-app", area="heap"}
  /
jvm_memory_max_bytes{job="java-app", area="heap"}
```

Every stored heap sample from the last hour. The `[1h]` is the historical part:

```promql
jvm_memory_used_bytes{job="java-app", area="heap"}[1h]
```

Grow the heap, wait at least one scrape (15 seconds), then run the used-heap query again:

```bash
kubectl -n lab port-forward svc/java-app 8080:8080
curl -X POST "http://localhost:8080/memory/hold?megabytes=32"
```

Other series worth graphing beside the heap:

```promql
# GC pauses per second over a 1 minute window
rate(jvm_gc_pause_seconds_count{job="java-app"}[1m])
```

```promql
# Time spent in GC, seconds per second, over a 1 minute window
rate(jvm_gc_pause_seconds_sum{job="java-app"}[1m])
```

```promql
jvm_threads_live_threads{job="java-app"}
```

```promql
process_cpu_usage{job="java-app"}
```

`job="java-app"` comes from the Service label `app`, via `jobLabel: app` on the ServiceMonitor. The app also adds `application="demo"` on each metric line. Either label selects this process.

Each ready pod is its own series. With more than one replica, add `pod` to see a single JVM:

```promql
jvm_memory_used_bytes{job="java-app", area="heap", pod="java-app-xxxxx"}
```

## Python

Latest custom gauge:

```promql
python_queue_depth{job="python-app"}
```

Raise it, wait one scrape, then query again:

```bash
kubectl -n lab port-forward svc/python-app 8000:8000
curl -X POST "http://localhost:8000/queue/add?n=3"
```

Request rate and time spent in `/work`:

```promql
sum by (pod) (rate(python_requests_total{job="python-app"}[1m]))
```

```promql
sum by (pod) (rate(python_work_seconds_sum{job="python-app"}[1m]))
```

`prometheus_client` also publishes process memory on the same page:

```promql
process_resident_memory_bytes{job="python-app"}
```

## After the Java pod is gone

Stop the process:

```bash
kubectl -n lab delete pod -l app=java-app
```

Kubernetes will start a replacement pod because the Deployment still asks for one replica. Until that new pod is scraped, the queries above show the last samples from the old process.

To leave the app down on purpose, scale it to zero first:

```bash
kubectl -n lab scale deployment/java-app --replicas=0
```

The latest-value query may show a gap or go stale. The range query still returns the samples Prometheus stored before the delete:

```promql
jvm_memory_used_bytes{job="java-app", area="heap"}[1h]
```

Highest heap used in that hour, in mebibytes:

```promql
max_over_time(jvm_memory_used_bytes{job="java-app", area="heap"}[1h]) / 1024 / 1024
```

Bring the app back:

```bash
kubectl -n lab scale deployment/java-app --replicas=1
```

The new JVM starts near an empty heap. On a graph, that looks like a drop. The climb from before the delete remains to the left of the drop. That left-hand side is the history you use when the process has already crashed.
