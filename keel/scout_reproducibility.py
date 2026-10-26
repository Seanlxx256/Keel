"""Explicit training policy; recorded state is not a validated resume API."""
import os
import random


def validate_policy(policy):
    if policy not in ('legacy', 'strict'):
        raise ValueError('Unknown training reproducibility policy')
    return policy


def configure_environment(policy):
    validate_policy(policy)
    if policy == 'strict':
        # Called before importing Torch/initializing CUDA in the training process.
        configured = os.environ.get('CUBLAS_WORKSPACE_CONFIG')
        if configured not in (None, ':4096:8'):
            raise ValueError('Strict training requires CUBLAS_WORKSPACE_CONFIG=:4096:8')
        os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'


def configure_torch(torch, policy):
    validate_policy(policy)
    if policy == 'strict':
        if torch.cuda.is_initialized():
            raise RuntimeError('Strict training requires a fresh process before CUDA initialization')
        torch.use_deterministic_algorithms(True)
    return {
        'policy': policy,
        'deterministic_algorithms': torch.are_deterministic_algorithms_enabled(),
        'cublas_workspace_config': os.environ.get('CUBLAS_WORKSPACE_CONFIG'),
        'cudnn_deterministic': torch.backends.cudnn.deterministic,
        'cudnn_benchmark': torch.backends.cudnn.benchmark,
        'matmul_tf32': torch.backends.cuda.matmul.allow_tf32,
        'cuda_version': torch.version.cuda,
        'scope': 'Recorded process configuration; no cross-device bitwise guarantee',
    }


def rng_state(torch):
    import numpy
    return {'python': random.getstate(), 'numpy': numpy.random.get_state(),
            'torch_cpu': torch.get_rng_state(), 'torch_cuda': torch.cuda.get_rng_state_all(),
            'scope': 'Post-update state inventory; checkpoint resume is not implemented'}


def seed_training(torch, policy, seed=42):
    validate_policy(policy)
    if policy == 'strict':
        import numpy
        random.seed(seed)
        numpy.random.seed(seed)
    torch.manual_seed(seed)
