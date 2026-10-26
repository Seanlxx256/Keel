"""Explicit repeated-KV SDPA route for the measured Windows training backend."""


def repeated_kv_sdpa(module,query,key,value,attention_mask,dropout=0.0,scaling=None,is_causal=None,**kwargs):
    import torch
    from torch.nn.attention import sdpa_kernel,SDPBackend
    from transformers.integrations.sdpa_attention import repeat_kv
    if kwargs.get('sliding_window') is not None:raise ValueError('Sliding attention not supported by this smoke route')
    key=repeat_kv(key,module.num_key_value_groups)
    value=repeat_kv(value,module.num_key_value_groups)
    if attention_mask is not None and attention_mask.ndim==4:
        attention_mask=attention_mask[:,:,:,:key.shape[-2]]
    if is_causal is None:is_causal=query.shape[2]>1 and attention_mask is None and getattr(module,'is_causal',True)
    # GQA enable_gqa=True in Torch2.5 prevents the efficient kernel. Explicit
    # KV repetition preserves grouped attention while allowing this backend.
    backend=SDPBackend.EFFICIENT_ATTENTION if query.device.type=='cuda' else SDPBackend.MATH
    with sdpa_kernel(backend):
        result=torch.nn.functional.scaled_dot_product_attention(query,key,value,
            attn_mask=attention_mask,dropout_p=dropout,scale=scaling,is_causal=is_causal)
    return result.transpose(1,2).contiguous(),None


def register_attention():
    from transformers.modeling_utils import ALL_ATTENTION_FUNCTIONS
    from transformers.masking_utils import ALL_MASK_ATTENTION_FUNCTIONS
    name='keel_repeated_kv_sdpa'
    ALL_ATTENTION_FUNCTIONS.register(name,repeated_kv_sdpa)
    ALL_MASK_ATTENTION_FUNCTIONS.register(name,ALL_MASK_ATTENTION_FUNCTIONS['sdpa'])
    return name
