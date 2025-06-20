export function getBackendUrl(gpu: number) {
  if (gpu === 0 || gpu === 1) return "http://backend-gpu0-service:9898";
  if (gpu === 2 || gpu === 3) return "http://backend-gpu1-service:9898";
  // fallback to load balancer or default
  return "http://backend-loadbalancer-service:9898";
}