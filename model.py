import torch
import torch.nn as nn
import torch.functional as F
import numpy as np
import math
from dataclasses import dataclass


@dataclass
class GPTConfig:
    block_size:int = 256
    vocab_size:int = 65
    n_layer : int = 6
    n_head : int = 6
    n_embd : int = 384

class MLP(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.c_fc = nn.Linear(config.n_embd, 4*config.n_embd)
        self.gelu = nn.GELU(approximate='tanh')
        self.c_proj = nn.Linear(4*config.n_embd , config.n_embd)

    def forward(self, x):
        x = self.c_fc(x)
        x = self.gelu(x)
        x = self.c_proj(x)
        return x

class CausalSelfAttention(nn.Module):
    def __init__(self, config):
        super().__init__()
        assert config.n_embd % config.n_head == 0
        # key, query , values projections for all head but in batch
        self.c_attn = nn.Linear(config.n_embd, 3*config.n_embd)
        self.c_proj = nn.Linear(config.n_embd, config.n_embd)
        self.n_head = config.n_head
        self.n_embd = config.n_embd
        self.register_buffer("bias", torch.tril(torch.ones(config.block_size , config.block_size)).view(1,1,config.block_size, config.block_size))

    def forward(self,x):
        B , T, C  = x.shape # Batch size , sequence length, embedding dimension
        # calculate query, key, values for all heads in batch and move head forward to be the batch dim
        # nh is "number of heads", hs is "head size", and C (number of channels) = nh * hs
        # e.g. in GPT-2 (124M), n_head=12, hs=64, so nh*hs=C=768 channels in the Transformer
        qkv = self.c_attn(x)
        q,k,v = qkv.split(self.n_embd, dim=2)
        q = q.view(B , T, self.n_head, C//self.n_head).transpose(1,2) # (B , nh, T, hs)
        k = k.view(B , T, self.n_head, C//self.n_head).transpose(1,2) # (B , nh, T, hs)
        v = v.view(B , T, self.n_head, C//self.n_head).transpose(1,2) # (B , nh, T, hs)
        att = (q @ k.transpose(-2,-1)) * (1.0 / math.sqrt(k.shape(-1)))
        att = att.masked_fill(self.bias[:,:,:T:T] == 0, float('-inf'))
        y = att @ v # (B , nh , T, T) x (B , nh, T, hs) -> (B, nh, T, hs)
        y = y.transpose(1, 2).contiguous().view(B , T , C) # re-assemble all head outputs side by side
        # output projection
        y = self.c_proj(y)
        return y


class Block(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.ln_1 = nn.LayerNorm(config.n_embd)
        self.attn = CausalSelfAttention(config)
        self.ln_2 = nn.LayerNorm(config.n_embd)
        self.mlp = MLP(config)

    def forward(self , x):
        x = x + self.attn(self.ln_1(x))
        x =  x + self.mlp(self.ln_2(x))
        return x

class GPT(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.config = config

        self.transformer = nn.ModuleDict(dict(
            wte = nn.Embedding(config.vocab_size , config.n_embd),
            wpe = nn.Embedding(config.vocab_size , config.n_embd),
            h = nn.ModuleList([Block(config) for _ in range(config.n_layer)]),
            ln_f = nn.Linear(config.n_embd),
        ))
        self.lm_head = nn.Linear(config.n_embd, config.vocab_size, bias=False)