# Prometheus lab — setup guide

This guide shows how to install Prometheus with Helm and collect numbers from a Java app and a Python app.

The apps run in a folder named `lab`. Prometheus, Grafana, and Alertmanager run in a folder named `monitoring`. In Kubernetes these folders are called namespaces.

## How the apps get connected

Prometheus does not find the apps by itself. A helper called the **Prometheus Operator** does that.

A **ServiceMonitor** is a small config file. It says which app to collect from, which port, and which web page.

1. Install Prometheus with Helm. The install name is `kube-prometheus-stack`.
2. That install looks for every ServiceMonitor that has this label: `release: kube-prometheus-stack`.
3. The Operator reads those files and builds a list of apps.
4. Prometheus visits each healthy pod and saves the numbers.

To add an app, you do not change `helm/values.yaml`. You only add this label on the ServiceMonitor:

```yaml
metadata:
  labels:
    release: kube-prometheus-stack
```

The word after `release:` must be the Helm install name. This guide uses `kube-prometheus-stack`. If the install were named `monitoring`, the label would be `release: monitoring`.

`jobLabel: app` copies the app name onto the numbers. That is why the queries use `job="java-app"` and `job="python-app"`.

## Steps

Run these commands from the project folder.

### 1. Build the app images inside Minikube

```bash
minikube image build -t java-app:0.0.1 ./java-app
minikube image build -t python-app:0.0.1 ./python-app
```

Build the images inside Minikube. The cluster cannot see images that exist only on your laptop.

### 2. Create the apps

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/java-app.yaml
kubectl apply -f k8s/python-app.yaml
kubectl apply -f k8s/app-rules.yaml
```

The app files start one pod each. To run 10 of each:

```bash
kubectl -n lab scale deployment/java-app --replicas=10
kubectl -n lab scale deployment/python-app --replicas=10
```

Do not apply `k8s/prometheus.yaml`. Helm already installs Prometheus. That old file would start a second one.

### 3. Install Prometheus

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --version 92.14.1 \
  --namespace monitoring \
  --create-namespace \
  -f helm/values.yaml
```

Check that everything is running:

```bash
kubectl -n monitoring get pods
kubectl -n lab get pods,servicemonitor
```

### 4. Open the pages

Prometheus:

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090
```

Open http://localhost:9090

Grafana (the graphs page):

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
```

Open http://localhost:3000. Sign in as `admin` / `prom-operator`.

This setup runs 3 Prometheus pods (`shards: 3`). Each one collects from about one third of the app pods. One Prometheus page will not show every pod. That is normal.

### 5. Check the numbers

In Prometheus, open Graph, then Table, and run:

```promql
up{job="java-app"}
```

```promql
up{job="python-app"}
```

`1` means Prometheus reached that pod. `0` means it did not.

Java memory, in MB:

```promql
jvm_memory_used_bytes{job="java-app", area="heap"} / 1024 / 1024
```

Python queue size:

```promql
python_queue_depth{job="python-app"}
```

List of pods. This comes from kube-state-metrics:

```promql
kube_pod_info
```

How busy the machine is. This comes from node-exporter:

```promql
100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```

### 6. Send some traffic

Port-forward reaches only one pod. Run the commands inside the cluster so they can land on different pods.

```bash
kubectl -n lab run loadgen --rm -it --restart=Never \
  --image=curlimages/curl:8.11.1 -- sh
```

Inside that shell:

```sh
curl -s -X POST "http://java-app.lab.svc.cluster.local:8080/memory/hold?megabytes=8"
curl -s -X POST "http://python-app.lab.svc.cluster.local:8000/work?seconds=0.2"
curl -s -X POST "http://python-app.lab.svc.cluster.local:8000/queue/add?n=1"
```

Wait 30 seconds, then run the memory and queue queries again.

`/memory/hold` fills memory on the one Java pod that got the call. Keep `megabytes` between 1 and 64. The Java app can hold about 256 MB before it runs out of memory.

To free that memory and clear the Python queue:

```sh
curl -s -X POST "http://java-app.lab.svc.cluster.local:8080/memory/release"
curl -s -X POST "http://python-app.lab.svc.cluster.local:8000/queue/clear"
```

Each call hits one pod. Repeat them until the pods you filled go back down.

## The files

| File | Use it? | What it is |
| --- | --- | --- |
| `helm/values.yaml` | Yes, with the Helm command | Settings for Prometheus, Grafana, and the other tools |
| `k8s/namespace.yaml` | Yes | Creates the `lab` folder |
| `k8s/java-app.yaml` | Yes | Java app, its address, and its ServiceMonitor |
| `k8s/python-app.yaml` | Yes | Python app, its address, and its ServiceMonitor |
| `k8s/app-rules.yaml` | Yes | Alerts |
| `k8s/prometheus.yaml` | No | Old Prometheus install. Do not use it |

## helm/values.yaml

This file changes a few settings of the Helm install. Chart version is 92.14.1.

You do not add apps in this file. Apps are added with a ServiceMonitor label.

| Setting | Value | What it means |
| --- | --- | --- |
| `replicas` | `1` | One copy of each Prometheus group. On a real system use `2`, so one copy can die and collection still works. |
| `shards` | `3` | Split the pods across 3 Prometheus servers. Each server sees about one third of the pods. |
| `retention` | `2d` | Keep the numbers for 2 days. |
| `retentionSize` | `1500MB` | Do not let the saved numbers grow past this size. |
| `scrapeInterval` | `30s` | How often Prometheus collects from most things. Java and Python use 15s, set in their own files. |
| `resources` | small CPU and memory | How much CPU and memory each Prometheus pod can use. |
| disk | 2 GB | Where the numbers are saved. They stay after a restart. |
| Alertmanager `replicas` | `1` | One Alertmanager. On a real system use 3. |
| `grafana.adminPassword` | `prom-operator` | Grafana password. The user name is `admin`. |
| `grafana.persistence.enabled` | `false` | Grafana does not save your own graphs to disk. The built-in graphs come back after a restart. |
| `kube-state-metrics` | small CPU and memory | Gives the pod list, restarts, and deployment counts. |
| `prometheus-node-exporter` | small CPU and memory | Gives CPU, memory, and disk of the machine. It does not list pods. |
| `prometheusOperator` | small CPU and memory | The helper that reads ServiceMonitors. |
| `kubeEtcd.enabled` | `false` | Turned off. Minikube does not share these numbers. |
| `kubeControllerManager.enabled` | `false` | Same. |
| `kubeScheduler.enabled` | `false` | Same. |
| `kubeProxy.enabled` | `false` | Same. |

`replicas` times `shards` is the number of Prometheus pods. This file runs 1 × 3 = 3 pods.

### Collect from one folder only

By default Prometheus looks in every namespace. To look only in `lab`, add this under `prometheus.prometheusSpec` in `helm/values.yaml`, then run the Helm command again.

```yaml
serviceMonitorNamespaceSelector:
  matchLabels:
    kubernetes.io/metadata.name: lab
```

The ServiceMonitor still needs the label `release: kube-prometheus-stack`.

If you limit it to `lab` only, you stop collecting from Prometheus itself, Grafana, and the machine. Those live in `monitoring` and `kube-system`. To keep them, list all three folders:

```yaml
serviceMonitorNamespaceSelector:
  matchExpressions:
    - key: kubernetes.io/metadata.name
      operator: In
      values:
        - lab
        - monitoring
        - kube-system
```

## k8s/namespace.yaml

Creates the folder `lab`. The Java app, the Python app, the ServiceMonitors, and the alerts go here.

| Field | Value | What it means |
| --- | --- | --- |
| `name` | `lab` | Folder name |
| `app.kubernetes.io/part-of` | `prometheus-java-lab` | A label on the folder. This Helm install does not use it. |

## k8s/java-app.yaml

This file has three parts.

### The app (`Deployment`)

Starts the Java program.

| Field | Value | What it means |
| --- | --- | --- |
| `replicas` | `1` | How many pods to start. Change it with `kubectl scale`. |
| `image` | `java-app:0.0.1` | The image built in step 1. |
| port | `8080`, name `http` | The ServiceMonitor uses the name `http`. |
| readiness check | `/actuator/health/readiness` | If this fails, Prometheus skips the pod. |
| liveness check | `/actuator/health/liveness` | If this fails, Kubernetes restarts the pod. |
| memory limit | `512Mi` | The program may use up to 512 MB. Its Java memory is capped at 256 MB. |

Pages you can call:

| Call | What it does |
| --- | --- |
| `POST /memory/hold?megabytes=8` | Holds that much memory on the pod that received the call. Use 1 to 64. |
| `POST /memory/release` | Frees that memory on the pod that received the call. |
| `GET /actuator/prometheus` | The page Prometheus reads. |

### The address (`Service`)

A shared address for the Java pods, on port 8080. It sends traffic to pods labeled `app: java-app`.

You use this address to call the app. Prometheus does not collect from this shared address. It visits each healthy pod behind it.

### The ServiceMonitor

This is the file the Operator uses to connect the Java app to Prometheus.

| Field | Value | What it means |
| --- | --- | --- |
| `release` | `kube-prometheus-stack` | Must match the Helm install name. Without it, Prometheus ignores this app. |
| `app` | `java-app` | Becomes the query name `job="java-app"`. |
| `selector` | `app: java-app` | Which Service to use. |
| `jobLabel` | `app` | Says "use the `app` label as the job name". |
| `port` | `http` | Port 8080. |
| `path` | `/actuator/prometheus` | The metrics page. |
| `interval` | `15s` | Collect every 15 seconds. |

## k8s/python-app.yaml

Same three parts as the Java file. The differences are:

| Field | Value |
| --- | --- |
| Image | `python-app:0.0.1` |
| Port | `8000`, name `http` |
| Health check | `GET /health` |
| Memory limit | `128Mi` |
| Metrics page | `/metrics` |
| Label `release` | `kube-prometheus-stack` |
| Job name in queries | `job="python-app"` |

Pages you can call:

| Call | What it does |
| --- | --- |
| `POST /work?seconds=0.2` | Makes the pod wait. The wait shows up as `python_work_seconds`. Maximum is 5 seconds. |
| `POST /queue/add?n=1` | Raises `python_queue_depth` on that pod. |
| `POST /queue/clear` | Sets the queue on that pod back to 0. |
| `GET /metrics` | The page Prometheus reads. |

## k8s/app-rules.yaml

Alerts for the two apps. The file name in the cluster is `lab-apps`. It also needs the label `release: kube-prometheus-stack`, same as a ServiceMonitor.

| Alert | When it fires | How long it must stay true |
| --- | --- | --- |
| `JavaHeapFilling` | Java memory is more than 90% full | 5 minutes |
| `AppTargetDown` | Prometheus cannot reach a Java or Python pod | 2 minutes |

You can see the alerts in Alertmanager. This setup does not send them to email or Slack.

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093:9093
```

Open http://localhost:9093

## k8s/prometheus.yaml

Do not apply this file.

It is an older way to install Prometheus by hand, inside `lab`. Helm already installs Prometheus in `monitoring`. Applying this file starts a second Prometheus.

## What is running

| Piece | Folder | What it does |
| --- | --- | --- |
| Prometheus Operator | `monitoring` | Reads ServiceMonitors and alerts, and tells Prometheus what to collect |
| Prometheus | `monitoring` | Saves the numbers and checks the alerts |
| Alertmanager | `monitoring` | Shows the alerts |
| Grafana | `monitoring` | Shows graphs. It reads from Prometheus |
| kube-state-metrics | `monitoring` | Pod list, restarts, and deployment counts |
| node-exporter | `monitoring` | CPU, memory, and disk of the machine |
| Java and Python apps | `lab` | The apps. Each healthy pod is collected on its own |
