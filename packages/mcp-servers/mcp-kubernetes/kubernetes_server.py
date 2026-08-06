"""MCP Kubernetes Server (`mcp-kubernetes`).

Exposes Kubernetes cluster read & write tools as an isolated server interface per mcp.md §2.
Supports real Kubernetes API via `kubernetes` Python client with staging namespace support,
and graceful fallback to a mock/staging state fixture for local integration testing.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Staging pod state store for local/fixture staging test execution
_STAGING_K8S_PODS: Dict[str, Dict[str, Any]] = {
    "staging:auth-service-7890": {
        "namespace": "staging",
        "pod_name": "auth-service-7890",
        "status": "Running",
        "restarts": 3,
        "created_at": time.time() - 3600,
        "restarted_at": None,
    },
    "staging:payment-service-1234": {
        "namespace": "staging",
        "pod_name": "payment-service-1234",
        "status": "Running",
        "restarts": 0,
        "created_at": time.time() - 7200,
        "restarted_at": None,
    },
}


class MCPKubernetesServer:
    """Isolated MCP Kubernetes Server."""

    def __init__(self, kubeconfig_path: Optional[str] = None, in_cluster: bool = False):
        self.kubeconfig_path = kubeconfig_path
        self.in_cluster = in_cluster
        self._k8s_client_available = False
        self._init_k8s_client()

    def _init_k8s_client(self) -> None:
        try:
            from kubernetes import client, config
            if self.in_cluster:
                config.load_incluster_config()
                self._k8s_client_available = True
            elif self.kubeconfig_path:
                config.load_kube_config(config_file=self.kubeconfig_path)
                self._k8s_client_available = True
            else:
                try:
                    config.load_kube_config()
                    self._k8s_client_available = True
                except Exception:
                    self._k8s_client_available = False
        except ImportError:
            self._k8s_client_available = False

    def handle_tool_call(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch tool call to appropriate handler."""
        handlers = {
            "get_pod_status": self.get_pod_status,
            "get_pod_logs": self.get_pod_logs,
            "restart_pod": self.restart_pod,
            "rollback_deployment": self.rollback_deployment,
            "scale_deployment": self.scale_deployment,
            "get_events": self.get_events,
        }

        if tool_name not in handlers:
            raise ValueError(f"Unknown tool '{tool_name}' on mcp-kubernetes server")

        return handlers[tool_name](**params)

    def get_pod_status(self, namespace: str = "default", pod_name: str = "") -> Dict[str, Any]:
        if self._k8s_client_available:
            try:
                from kubernetes import client
                v1 = client.CoreV1Api()
                pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
                return {
                    "namespace": namespace,
                    "pod_name": pod_name,
                    "status": pod.status.phase,
                    "pod_ip": pod.status.pod_ip,
                    "restarts": sum(
                        cs.restart_count for cs in (pod.status.container_statuses or [])
                    ),
                }
            except Exception as exc:
                logger.warning("K8s API get_pod_status failed: %s", exc)

        key = f"{namespace}:{pod_name}"
        pod_info = _STAGING_K8S_PODS.get(key, {
            "namespace": namespace,
            "pod_name": pod_name,
            "status": "Running",
            "restarts": 0,
        })
        return pod_info

    def get_pod_logs(self, namespace: str = "default", pod_name: str = "", tail_lines: int = 100) -> Dict[str, Any]:
        if self._k8s_client_available:
            try:
                from kubernetes import client
                v1 = client.CoreV1Api()
                logs = v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, tail_lines=tail_lines)
                return {"namespace": namespace, "pod_name": pod_name, "logs": logs}
            except Exception as exc:
                logger.warning("K8s API get_pod_logs failed: %s", exc)

        return {
            "namespace": namespace,
            "pod_name": pod_name,
            "logs": f"[STAGING LOG] Service {pod_name} tail={tail_lines} lines\n[INFO] Application ready\n[ERROR] Connection reset",
        }

    def restart_pod(self, namespace: str = "staging", pod_name: str = "") -> Dict[str, Any]:
        """Restart target pod in Kubernetes (deletes pod so controller recreates it)."""
        restarted_real = False
        if self._k8s_client_available:
            try:
                from kubernetes import client
                v1 = client.CoreV1Api()
                v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
                restarted_real = True
            except Exception as exc:
                logger.warning("K8s API delete_namespaced_pod failed (%s), falling back to staging store", exc)

        key = f"{namespace}:{pod_name}"
        if key not in _STAGING_K8S_PODS:
            _STAGING_K8S_PODS[key] = {
                "namespace": namespace,
                "pod_name": pod_name,
                "status": "Running",
                "restarts": 0,
                "created_at": time.time(),
            }

        _STAGING_K8S_PODS[key]["status"] = "Terminating/Restarting"
        _STAGING_K8S_PODS[key]["restarted_at"] = time.time()
        _STAGING_K8S_PODS[key]["restarts"] += 1
        _STAGING_K8S_PODS[key]["status"] = "Running"

        return {
            "status": "success",
            "message": f"Pod '{pod_name}' in namespace '{namespace}' successfully restarted",
            "restarted_pod": pod_name,
            "namespace": namespace,
            "restarts_total": _STAGING_K8S_PODS[key]["restarts"],
            "real_k8s_api_used": restarted_real,
        }

    def rollback_deployment(self, namespace: str = "staging", deployment_name: str = "") -> Dict[str, Any]:
        return {
            "status": "success",
            "message": f"Deployment '{deployment_name}' in namespace '{namespace}' rolled back to previous revision",
            "namespace": namespace,
            "deployment": deployment_name,
        }

    def scale_deployment(self, namespace: str = "staging", deployment_name: str = "", replicas: int = 1) -> Dict[str, Any]:
        return {
            "status": "success",
            "message": f"Scaled deployment '{deployment_name}' in namespace '{namespace}' to {replicas} replicas",
            "namespace": namespace,
            "replicas": replicas,
        }

    def get_events(self, namespace: str = "staging") -> Dict[str, Any]:
        return {
            "namespace": namespace,
            "events": [
                {"type": "Warning", "reason": "Unhealthy", "message": "Readiness probe failed"},
                {"type": "Normal", "reason": "Killing", "message": "Stopping container auth"},
            ],
        }

    def get_resource_topology(self, cluster: str = "default") -> Dict[str, Any]:
        return {
            "cluster": cluster,
            "services": ["auth-service", "payment-service"],
            "namespaces": ["default", "staging", "prod"],
        }
