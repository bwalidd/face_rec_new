#!/bin/bash

# Kubernetes DNS Checker and Fixer Script
# This script diagnoses and fixes DNS resolution issues in Kubernetes clusters

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="face-recognition-system"
TEST_DOMAINS=("registry-1.docker.io" "google.com" "docker.io" "k8s.gcr.io")
REQUIRED_IMAGES=("coturn/coturn:latest" "bluenviron/mediamtx:latest")

# Function to print colored output
print_header() {
    echo -e "\n${PURPLE}================================${NC}"
    echo -e "${PURPLE}$1${NC}"
    echo -e "${PURPLE}================================${NC}\n"
}

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_fix() {
    echo -e "${GREEN}[FIX]${NC} $1"
}

# Function to run command and capture output
run_command() {
    local cmd="$1"
    local description="$2"
    
    print_status "Running: $description"
    if eval "$cmd" > /tmp/cmd_output 2>&1; then
        print_success "$description - OK"
        return 0
    else
        print_error "$description - FAILED"
        cat /tmp/cmd_output
        return 1
    fi
}

# Function to test DNS resolution from host
test_host_dns() {
    print_header "Testing Host DNS Resolution"
    
    local all_passed=true
    for domain in "${TEST_DOMAINS[@]}"; do
        print_status "Testing $domain..."
        if nslookup "$domain" > /dev/null 2>&1; then
            local ip=$(nslookup "$domain" | grep -A1 "Name:" | tail -1 | awk '{print $2}' 2>/dev/null || echo "Unknown")
            print_success "$domain resolves to $ip"
        else
            print_error "$domain resolution failed"
            all_passed=false
        fi
    done
    
    if [ "$all_passed" = true ]; then
        print_success "All host DNS tests passed"
        return 0
    else
        print_error "Host DNS resolution issues detected"
        return 1
    fi
}

# Function to test DNS resolution from pods
test_pod_dns() {
    print_header "Testing Pod DNS Resolution"
    
    # Find a running pod
    local pod=$(kubectl get pods -n "$NAMESPACE" --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    
    if [ -z "$pod" ]; then
        print_error "No running pods found in namespace $NAMESPACE"
        return 1
    fi
    
    print_status "Using pod: $pod"
    
    local all_passed=true
    for domain in "${TEST_DOMAINS[@]}"; do
        print_status "Testing $domain from pod..."
        if kubectl exec -n "$NAMESPACE" "$pod" -- python3 -c "
import socket
try:
    ip = socket.gethostbyname('$domain')
    print(f'$domain -> {ip}')
    exit(0)
except:
    exit(1)
" > /dev/null 2>&1; then
            print_success "$domain resolution from pod - OK"
        else
            print_error "$domain resolution from pod - FAILED"
            all_passed=false
        fi
    done
    
    if [ "$all_passed" = true ]; then
        print_success "All pod DNS tests passed"
        return 0
    else
        print_error "Pod DNS resolution issues detected"
        return 1
    fi
}

# Function to check CoreDNS status
check_coredns() {
    print_header "Checking CoreDNS Status"
    
    # Check if CoreDNS pods are running
    if ! kubectl get pods -n kube-system -l k8s-app=kube-dns --field-selector=status.phase=Running | grep -q coredns; then
        print_error "CoreDNS pods are not running properly"
        return 1
    fi
    
    print_success "CoreDNS pods are running"
    
    # Check CoreDNS logs for errors
    if kubectl logs -n kube-system -l k8s-app=kube-dns --tail=10 | grep -i error > /dev/null 2>&1; then
        print_warning "CoreDNS logs contain errors:"
        kubectl logs -n kube-system -l k8s-app=kube-dns --tail=5
    else
        print_success "No recent errors in CoreDNS logs"
    fi
    
    return 0
}

# Function to check failed pods
check_failed_pods() {
    print_header "Checking Failed Pods"
    
    local failed_pods=$(kubectl get pods -n "$NAMESPACE" --field-selector=status.phase!=Running,status.phase!=Succeeded -o jsonpath='{.items[*].metadata.name}' 2>/dev/null)
    
    if [ -z "$failed_pods" ]; then
        print_success "No failed pods found"
        return 0
    fi
    
    print_warning "Found failed pods: $failed_pods"
    
    for pod in $failed_pods; do
        print_status "Checking pod: $pod"
        kubectl describe pod "$pod" -n "$NAMESPACE" | grep -A 5 -B 5 -i "pull\|image\|error\|failed"
    done
    
    return 1
}

# Function to check node systemd-resolved
check_systemd_resolved() {
    print_header "Checking systemd-resolved Status"
    
    if systemctl is-active --quiet systemd-resolved; then
        print_success "systemd-resolved is active"
    else
        print_error "systemd-resolved is not active"
        return 1
    fi
    
    # Check DNS configuration
    print_status "Current DNS configuration:"
    cat /etc/resolv.conf | head -10
    
    return 0
}

# Function to test Docker registry connectivity
test_docker_registry() {
    print_header "Testing Docker Registry Connectivity"
    
    for image in "${REQUIRED_IMAGES[@]}"; do
        print_status "Testing connectivity to $image..."
        if timeout 30 docker manifest inspect "$image" > /dev/null 2>&1; then
            print_success "$image is accessible"
        else
            print_error "$image is not accessible"
            return 1
        fi
    done
    
    return 0
}

# FIXER FUNCTIONS

# Function to fix systemd-resolved
fix_systemd_resolved() {
    print_fix "Restarting systemd-resolved..."
    
    if sudo systemctl restart systemd-resolved; then
        print_success "systemd-resolved restarted successfully"
        sleep 3
        return 0
    else
        print_error "Failed to restart systemd-resolved"
        return 1
    fi
}

# Function to fix CoreDNS
fix_coredns() {
    print_fix "Restarting CoreDNS..."
    
    if kubectl rollout restart deployment/coredns -n kube-system; then
        print_status "Waiting for CoreDNS to be ready..."
        kubectl rollout status deployment/coredns -n kube-system --timeout=60s
        print_success "CoreDNS restarted successfully"
        sleep 5
        return 0
    else
        print_error "Failed to restart CoreDNS"
        return 1
    fi
}

# Function to manually pull images
fix_image_pull() {
    print_fix "Manually pulling required images..."
    
    for image in "${REQUIRED_IMAGES[@]}"; do
        print_status "Pulling $image..."
        if sudo docker pull "$image"; then
            print_success "$image pulled successfully"
        else
            print_warning "Failed to pull $image - will try alternative method"
        fi
    done
    
    return 0
}

# Function to restart failed pods
fix_failed_pods() {
    print_fix "Restarting failed pods..."
    
    local failed_pods=$(kubectl get pods -n "$NAMESPACE" --field-selector=status.phase!=Running,status.phase!=Succeeded -o jsonpath='{.items[*].metadata.name}' 2>/dev/null)
    
    if [ -z "$failed_pods" ]; then
        print_success "No failed pods to restart"
        return 0
    fi
    
    for pod in $failed_pods; do
        print_status "Deleting pod: $pod"
        kubectl delete pod "$pod" -n "$NAMESPACE" --force --grace-period=0
    done
    
    print_status "Waiting for pods to restart..."
    sleep 10
    
    return 0
}

# Function to configure alternative DNS
fix_dns_alternative() {
    print_fix "Configuring alternative DNS servers..."
    
    # Backup current resolv.conf
    sudo cp /etc/resolv.conf /etc/resolv.conf.backup
    
    # Add Google DNS as backup
    cat << EOF | sudo tee /etc/resolv.conf.new
nameserver 8.8.8.8
nameserver 8.8.4.4
nameserver 1.1.1.1
$(cat /etc/resolv.conf)
EOF
    
    sudo mv /etc/resolv.conf.new /etc/resolv.conf
    print_success "Alternative DNS servers configured"
    
    return 0
}

# Main diagnostic function
run_diagnostics() {
    print_header "Kubernetes DNS Diagnostics Starting"
    
    local issues=0
    
    # Test host DNS
    if ! test_host_dns; then
        ((issues++))
    fi
    
    # Test pod DNS
    if ! test_pod_dns; then
        ((issues++))
    fi
    
    # Check CoreDNS
    if ! check_coredns; then
        ((issues++))
    fi
    
    # Check failed pods
    if ! check_failed_pods; then
        ((issues++))
    fi
    
    # Check systemd-resolved
    if ! check_systemd_resolved; then
        ((issues++))
    fi
    
    # Test Docker registry
    if ! test_docker_registry; then
        ((issues++))
    fi
    
    echo -e "\n${PURPLE}================================${NC}"
    if [ $issues -eq 0 ]; then
        print_success "All diagnostics passed! No issues detected."
        return 0
    else
        print_warning "Found $issues issue(s). Running auto-fix..."
        return 1
    fi
}

# Main fix function
run_fixes() {
    print_header "Running Automatic Fixes"
    
    # Fix systemd-resolved
    fix_systemd_resolved
    
    # Test host DNS again
    if ! test_host_dns; then
        print_warning "Host DNS still failing, trying alternative DNS..."
        fix_dns_alternative
    fi
    
    # Fix CoreDNS
    fix_coredns
    
    # Try to pull images manually
    fix_image_pull
    
    # Restart failed pods
    fix_failed_pods
    
    print_header "Waiting for system to stabilize..."
    sleep 15
    
    # Run diagnostics again
    print_header "Re-running Diagnostics After Fixes"
    if run_diagnostics; then
        print_success "All issues have been resolved!"
        return 0
    else
        print_warning "Some issues may still exist. Manual intervention might be required."
        return 1
    fi
}

# Function to show usage
show_usage() {
    echo "Kubernetes DNS Checker and Fixer"
    echo "Usage: $0 [option]"
    echo ""
    echo "Options:"
    echo "  check     - Run diagnostics only"
    echo "  fix       - Run diagnostics and auto-fix issues"
    echo "  status    - Show current cluster status"
    echo "  help      - Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 check    # Diagnose issues only"
    echo "  $0 fix      # Diagnose and fix issues"
    echo ""
}

# Function to show cluster status
show_status() {
    print_header "Current Cluster Status"
    
    print_status "Pods in namespace $NAMESPACE:"
    kubectl get pods -n "$NAMESPACE" -o wide
    
    print_status "\nServices in namespace $NAMESPACE:"
    kubectl get services -n "$NAMESPACE"
    
    print_status "\nNode status:"
    kubectl get nodes -o wide
    
    print_status "\nCoreaDNS pods:"
    kubectl get pods -n kube-system -l k8s-app=kube-dns
}

# Main script logic
main() {
    local action=${1:-fix}
    
    case "$action" in
        "check")
            run_diagnostics
            ;;
        "fix")
            if ! run_diagnostics; then
                run_fixes
            fi
            ;;
        "status")
            show_status
            ;;
        "help"|"-h"|"--help")
            show_usage
            ;;
        *)
            print_error "Unknown option: $action"
            show_usage
            exit 1
            ;;
    esac
}

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    print_error "kubectl is not installed or not in PATH"
    exit 1
fi

# Check if running as root for some operations
if [[ $EUID -ne 0 ]] && [[ "$1" == "fix" ]]; then
    print_warning "Some fixes require root privileges. You may be prompted for sudo password."
fi

# Run main function
main "$@"