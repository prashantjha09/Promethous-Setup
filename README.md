# Prometheus with Java and Python applications

A small lab for one question:

**If the Java process crashes, where does the heap history live, and how do you read it?**

Prometheus does not read the dead JVM. It already copied the numbers while the app was alive.

## The three roles

```
Java app                         Prometheus                         You
--------                         ----------                         ---
exposes /actuator/prometheus --> scrapes every 15s and stores  --> query the stored series
current heap, GC, threads        samples on its own disk            even after the app is gone
```

1. **Java app** — Micrometer reads the JVM and publishes text metrics on an HTTP endpoint.
2. **Prometheus** — On a timer it fetches that page and appends each sample to its time-series database (TSDB).
3. **You** — You ask Prometheus for a time range. The answer comes from Prometheus disk, not from the JVM.

When the JVM exits, its heap, thread stacks, and live objects are gone. The samples Prometheus already stored stay until its retention window expires (15 days in this lab).

## What you can and cannot reconstruct

| After a crash | Still available | Gone with the process |
| --- | --- | --- |
| Heap used over the last hour | Yes, one point every scrape | The objects that filled the heap |
| How close used heap got to max heap | Yes | A heap dump (`hprof`) unless something wrote one at exit |
| GC pauses and GC count | Yes | Local variables and the exact stack at the moment of death |
| Process CPU and thread counts | Yes | Logs that were only in memory |

Prometheus answers “how did memory trend before the crash?” A heap dump answers “which objects were alive?” This lab is the first question.

The last sample is at most one scrape interval old. With a 15 second scrape, a crash at 10:00:14 still has a point from 10:00:00. It does not have a point from the exact millisecond of the crash.

## Heap metrics this lab will use

Micrometer publishes these without extra code:

| Metric | Meaning |
| --- | --- |
| `jvm_memory_used_bytes{area="heap"}` | Bytes currently occupied on the heap |
| `jvm_memory_max_bytes{area="heap"}` | Heap ceiling (`-Xmx`). `-1` if the pool has no fixed max |
| `jvm_memory_used_bytes{area="nonheap"}` | Metaspace, code cache, and other non-heap areas |
| `jvm_gc_pause_seconds_count` | How many GC pauses have happened |
| `jvm_gc_pause_seconds_sum` | Total seconds spent in GC |
| `jvm_threads_live_threads` | Live thread count |
| `process_cpu_usage` | Process CPU, 0.0 to 1.0 per core-equivalent |

A memory leak in the trend looks like `jvm_memory_used_bytes` climbing toward `jvm_memory_max_bytes`, with GC running more often and freeing less each time.

## How a query reads history

Prometheus keeps each series as `(timestamp, value)` pairs. This returns every heap sample from the last hour:

```promql
jvm_memory_used_bytes{area="heap", application="demo"}[1h]
```

The `[1h]` range selector is what makes it historical. Without the brackets, Prometheus returns only the latest sample.

Heap fill ratio over that same hour:

```promql
jvm_memory_used_bytes{area="heap", application="demo"}
  /
jvm_memory_max_bytes{area="heap", application="demo"}
```

## How Kubernetes fits

Same three roles, in the namespace `lab`. Prometheus Operator owns the Prometheus process. Each app owns a ServiceMonitor. There is no scrape list inside Prometheus.

```
namespace: lab

java-app Deployment (n pods)     Service java-app          ServiceMonitor java-app
python-app Deployment (n pods)   Service python-app        ServiceMonitor python-app
        |                                |                            |
        | ready pod IPs                  | selects those Services     |
        v                                v                            v
                          Prometheus CR  ---- operator writes one target per pod
                          TSDB on a PersistentVolumeClaim
```

A Service ClusterIP is a single address. kube-proxy sends each connection to one ready pod. Scraping `java-app.lab.svc.cluster.local` once every 15 seconds stores one pod per interval and mixes those JVMs into one series.

A ServiceMonitor selects the Service by label. The operator discovers the Endpoints (or EndpointSlices) of that Service and configures one scrape target per ready pod IP. Forty ready pods means forty scrapes every interval, each stored with its own `pod` and `instance` labels. A pod that is not ready is not in the Endpoints, so it is not scraped.

Java and Python keep different ports and paths on their own ServiceMonitors:

| ServiceMonitor | Service label | Port | Path |
| --- | --- | --- | --- |
| `java-app` | `app: java-app` | `http` (8080) | `/actuator/prometheus` |
| `python-app` | `app: python-app` | `http` (8000) | `/metrics` |

`jobLabel: app` copies that Service label onto the Prometheus `job` label, so queries use `job="java-app"` and `job="python-app"`. Adding another app means another Deployment, Service, and ServiceMonitor. The Prometheus object stays as it is.

The Service name still matters: it is how the ServiceMonitor finds pods, and how you port-forward. It is not the scrape URL.

Two disks, two lifetimes:

| Disk | Attached to | Survives an app crash | Survives a Prometheus restart |
| --- | --- | --- | --- |
| JVM heap, or the Python process | the app container | No | — |
| Prometheus TSDB | the claim created by the Prometheus CR | Yes | Yes |

The Prometheus volume is created by the Helm chart. The operator runs Prometheus as a StatefulSet and mounts that volume. `emptyDir` would be wiped when the pod is rescheduled.

The chart loads every ServiceMonitor and PrometheusRule that has the label `release: kube-prometheus-stack`, in any namespace. The Java and Python monitors carry that label. `jobLabel: app` is unchanged.

## Kubernetes objects

Install the platform with Helm. The chart installs the operator, Prometheus, Alertmanager, Grafana, node-exporter, and kube-state-metrics:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --version 92.14.1 \
  --namespace monitoring \
  --create-namespace \
  -f helm/values.yaml
```

Then the lab objects:

| Object | Name | Job |
| --- | --- | --- |
| Namespace | `lab` | Keeps this exercise separate from other workloads |
| Deployment | `java-app` | JVM with a 256 MiB heap. Scale this to scrape every replica |
| Service | `java-app` | Selects Java pods. The monitor reads its endpoints |
| ServiceMonitor | `java-app` | Path `/actuator/prometheus`, every ready Java pod |
| Deployment | `python-app` | Python process on port 8000 |
| Service | `python-app` | Selects Python pods |
| ServiceMonitor | `python-app` | Path `/metrics`, every ready Python pod |
| PrometheusRule | `lab-apps` | Heap and target-down alerts, selected by the Helm release label |
| Prometheus, Alertmanager, Grafana | Helm release `kube-prometheus-stack` | Operator, scrapers, alerts, and dashboards in namespace `monitoring` |

On Minikube the cluster runtime is containerd inside the node, not the Docker or Podman store on your laptop. Build the images there so `imagePullPolicy: IfNotPresent` can see `java-app:0.0.1` and `python-app:0.0.1`:

```bash
minikube image build -t java-app:0.0.1 ./java-app
minikube image build -t python-app:0.0.1 ./python-app
```

Minikube's default StorageClass is `standard` (`k8s.io/minikube-hostpath`). The Prometheus volume claim leaves `storageClassName` empty and binds to that class.

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/java-app.yaml
kubectl apply -f k8s/python-app.yaml
kubectl apply -f k8s/app-rules.yaml
```

`k8s/prometheus.yaml` is the earlier hand-written Prometheus. Leave it unapplied while the Helm release is installed.

Open the UIs:

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
```

Grafana signs in as `admin` / `prom-operator`.

## Files

| # | File | What it is |
| --- | --- | --- |
| 1 | `README.md` | This explanation |
| 2 | `java-app/` | Spring Boot app that exposes JVM metrics, plus its Dockerfile |
| 3 | `python-app/` | Python service that exposes `/metrics`, plus its Dockerfile |
| 4 | `k8s/namespace.yaml` | The `lab` namespace |
| 5 | `k8s/java-app.yaml` | Deployment, Service, and ServiceMonitor for the JVM |
| 6 | `k8s/python-app.yaml` | Deployment, Service, and ServiceMonitor for Python |
| 7 | `k8s/prometheus.yaml` | Earlier hand-written Prometheus. Do not apply it beside Helm |
| 8 | `k8s/app-rules.yaml` | PrometheusRule for the Java and Python apps |
| 9 | `helm/values.yaml` | kube-prometheus-stack values for this cluster |
| 10 | `queries.md` | Queries to run after both apps are scraped |
| 11 | `production-architecture.md` | Helm, ServiceMonitor, scrape path, replicas, and shards for production |
| 12 | `confluence-guide.md` | Beginner setup guide for Confluence: steps and every Helm and k8s file |
