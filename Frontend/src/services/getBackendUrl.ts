export function getBackendUrl(gpu: number) {
  if (gpu === 0) return "http://backend-gpu0-service:9898";
  if (gpu === 1) return "http://backend-gpu1-service:9898";
  // fallback to load balancer or default
  return "http://backend-loadbalancer-service:9898";
} 