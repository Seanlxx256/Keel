import unittest
from types import SimpleNamespace


class ScoutAttentionTests(unittest.TestCase):
    def setUp(self):
        try:
            import torch,transformers,peft
            self.torch=torch
        except ImportError:self.skipTest('Explicit training dependency environment required')

    def test_repeated_grouped_attention_matches_full_math_values_and_gradients(self):
        from keel.scout_attention import repeated_kv_sdpa
        torch=self.torch;torch.manual_seed(42)
        for masked in (False,True):
            q=torch.randn(1,4,7,8,requires_grad=True)
            k=torch.randn(1,2,7,8,requires_grad=True);v=torch.randn(1,2,7,8,requires_grad=True)
            mask=torch.ones(7,7,dtype=torch.bool).tril()[None,None] if masked else None
            actual,_=repeated_kv_sdpa(SimpleNamespace(num_key_value_groups=2,is_causal=True),q,k,v,mask)
            expected=torch.nn.functional.scaled_dot_product_attention(q,k.repeat_interleave(2,dim=1),
                v.repeat_interleave(2,dim=1),attn_mask=mask,is_causal=not masked).transpose(1,2).contiguous()
            torch.testing.assert_close(actual,expected)
            a=torch.autograd.grad(actual.square().sum(),(q,k,v),retain_graph=True)
            b=torch.autograd.grad(expected.square().sum(),(q,k,v))
            for x,y in zip(a,b):torch.testing.assert_close(x,y)

    def test_real_tiny_qwen_lora_registry_mask_and_checkpoint_backward(self):
        import torch
        from transformers import Qwen3Config,Qwen3ForCausalLM
        from peft import LoraConfig,get_peft_model
        from keel.scout_attention import register_attention
        config=Qwen3Config(vocab_size=64,hidden_size=32,intermediate_size=64,num_hidden_layers=1,
            num_attention_heads=4,num_key_value_heads=2,head_dim=8)
        config._attn_implementation=register_attention()
        model=get_peft_model(Qwen3ForCausalLM(config),LoraConfig(r=2,target_modules=['q_proj','v_proj'],task_type='CAUSAL_LM'))
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
        model.train();ids=torch.tensor([[1,2,3,4,5,6]])
        loss=model(input_ids=ids,labels=ids,use_cache=False).loss;loss.backward()
        self.assertTrue(torch.isfinite(loss))
        self.assertTrue(any(p.grad is not None and p.grad.abs().sum()>0 for p in model.parameters() if p.requires_grad))
