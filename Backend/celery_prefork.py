import os

# GPU configuration
app.conf.update(
    gpu_count=2,
    gpu_devices="0,1",
    node_type=os.environ.get('NODE_TYPE', 'master'),
    cuda_visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES', '0,1'),
    pytorch_cuda_alloc_conf='max_split_size_mb:256',
    nccl_debug='INFO',
    nccl_ib_disable='1',
    nccl_p2p_disable='1',
    cuda_version='12.2' if os.environ.get('NODE_TYPE', 'master') == 'master' else '12.4',
    cuda_launch_blocking='0',
    omp_num_threads='4',
    malloc_trim_threshold='100000',
) 