import torch

from contextlib import contextmanager
from typing import Union, Tuple


_size_2_t = Union[int, Tuple[int, int]]


class LinearWithLoRA(torch.nn.Module):
    def __init__(
            self,
            in_features: int,
            out_features: int,
            bias: bool = True,
            device=None,
            dtype=None) -> None:
        super().__init__()
        self.weight = None
        self.up = None
        self.down = None
        self.bias = None
        self.in_features = in_features
        self.out_features = out_features
        self.device = device
        self.dtype = dtype

    def bind_lora(self, weight):
        self.weight = weight

    def unbind_lora(self):
        if self.up is not None and self.down is not None:  # SAI's model is weird and needs this
            self.weight = None

    def forward(self, x):
        if self.weight is None:
            return None  # A1111 needs first_time_calculation

        if self.up is not None and self.down is not None:
            weight = self.weight.to(x.device) + torch.mm(self.up, self.down).to(x.device)
        else:
            weight = self.weight.to(x.device)

        return torch.nn.functional.linear(x, weight, self.bias.to(x.device) if self.bias is not None else None)


class Conv2dWithLoRA(torch.nn.Module):
    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: _size_2_t,
        stride: _size_2_t = 1,
        padding: Union[str, _size_2_t] = 0,
        dilation: _size_2_t = 1,
        groups: int = 1,
        bias: bool = True,
        padding_mode: str = 'zeros',
        device=None,
        dtype=None
    ) -> None:
        super().__init__()
        self.stride = stride
        self.padding = padding
        self.dilation = dilation
        self.groups = groups
        self.weight = None
        self.bias = None
        self.up = None
        self.down = None
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.kernel_size = kernel_size
        self.padding_mode = padding_mode
        self.device = device
        self.dtype = dtype

    def bind_lora(self, weight):
        self.weight = weight

    def unbind_lora(self):
        if self.up is not None and self.down is not None:  # SAI's model is weird and needs this
            self.weight = None

    def forward(self, x):
        if self.weight is None:
            return None  # A1111 needs first_time_calculation

        if self.up is not None and self.down is not None:
            weight = self.weight.to(x.device) + torch.mm(self.up.flatten(start_dim=1), self.down.flatten(start_dim=1)).reshape(self.weight.shape).to(x.device)
        else:
            weight = self.weight.to(x.device)

        return torch.nn.functional.conv2d(x, weight, self.bias.to(x.device) if self.bias is not None else None,
                                          self.stride, self.padding, self.dilation, self.groups)


@contextmanager
def controlnet_lora_hijack():
    linear, conv2d = torch.nn.Linear, torch.nn.Conv2d
    torch.nn.Linear, torch.nn.Conv2d = LinearWithLoRA, Conv2dWithLoRA
    try:
        yield
    finally:
        torch.nn.Linear, torch.nn.Conv2d = linear, conv2d


def recursive_set(obj, key, value):
    if obj is None:
        return
    if '.' in key:
        k1, k2 = key.split('.', 1)
        recursive_set(getattr(obj, k1, None), k2, value)
    else:
        setattr(obj, key, value)


def force_load_state_dict(model, state_dict):
    for k in list(state_dict.keys()):
        recursive_set(model, k, torch.nn.Parameter(state_dict[k]))
        del state_dict[k]
    return


def recursive_bind_lora(obj, key, value):
    if obj is None:
        return
    if '.' in key:
        k1, k2 = key.split('.', 1)
        recursive_bind_lora(getattr(obj, k1, None), k2, value)
    else:
        if key == 'weight':
            if hasattr(obj, 'bind_lora'):
                # obj.bind_lora(torch.nn.Parameter(value))
                obj.bind_lora(value)


def bind_control_lora(base_model, control_lora_model):
    sd = base_model.state_dict()
    for k, v in sd.items():
        recursive_bind_lora(control_lora_model, k, v)


def torch_dfs(model: torch.nn.Module):
    result = [model]
    for child in model.children():
        result += torch_dfs(child)
    return result


def unbind_control_lora(control_lora_model):
    for m in torch_dfs(control_lora_model):
        if hasattr(m, 'unbind_lora'):
            m.unbind_lora()
    return
