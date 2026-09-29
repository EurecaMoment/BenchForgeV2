# 生成模型安装

模型工具通过独立解释器加载权重，结果写入服务的任务目录。
可复用已有合规安装；不要复制其他工程的私有配置。
以下路径示例使用 `$HOME/bfv2-models`，替换为自己的磁盘目录。
生成工具使用显存门槛和进程锁，只在显式允许且空闲的 GPU 上运行。
FLUX/SAM3D 建议服务 GPU 至少 32–48 GB；Isaac 使用另一台 Windows 桌面。

## FLUX.2 Klein 参考图

已使用的运行时版本：Torch 2.8.0/cu126、Diffusers 0.40.0、Transformers 5.16.1、Accelerate 1.14.0。

```bash
export BF_MODELS="$HOME/bfv2-models"
mkdir -p "$BF_MODELS"
python3.11 -m venv "$BF_MODELS/flux-env"
"$BF_MODELS/flux-env/bin/pip" install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu126
"$BF_MODELS/flux-env/bin/pip" install diffusers==0.40.0 transformers==5.16.1 accelerate==1.14.0 sentencepiece protobuf Pillow huggingface_hub
"$BF_MODELS/flux-env/bin/hf" download black-forest-labs/FLUX.2-klein-9B --local-dir "$BF_MODELS/FLUX.2-klein-9B"
```

在 `models.flux` 中填写该环境的 `bin/python` 和权重目录。
权重访问如需授权，在 Hugging Face 模型页按条款申请后用 `hf auth login` 登录。
worker 运行时使用本地权重，不在每次任务中联网下载。

## SAM3 分割

```bash
git clone https://github.com/facebookresearch/sam3.git "$BF_MODELS/sam3-source"
git -C "$BF_MODELS/sam3-source" checkout 847e1a3b15115a04c87c0760297f044f0555d970
python3.11 -m venv "$BF_MODELS/sam3-env"
"$BF_MODELS/sam3-env/bin/pip" install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu126
"$BF_MODELS/sam3-env/bin/pip" install -e "$BF_MODELS/sam3-source" opencv-python pycocotools einops scipy Pillow
"$BF_MODELS/sam3-env/bin/hf" download facebook/sam3 --local-dir "$BF_MODELS/sam3"
```

设置 `models.sam3.python/path` 和 `sources.sam3`；权重目录应包含 `sam3.pt`。
本仓库包含实际多实例分割 worker，支持文本和实例框提示。

## SAM 3D Objects 资产生成

```bash
git clone https://github.com/facebookresearch/sam-3d-objects.git "$BF_MODELS/sam3d-source"
git -C "$BF_MODELS/sam3d-source" checkout 01417d16fb5cc762a60f370c1bf7f59d603ddfaf
cd "$BF_MODELS/sam3d-source"
mamba env create -f environments/default.yml
mamba activate sam3d-objects
export PIP_EXTRA_INDEX_URL="https://pypi.ngc.nvidia.com https://download.pytorch.org/whl/cu121"
pip install -e '.[dev]'
pip install -e '.[p3d]'
export PIP_FIND_LINKS="https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.5.1_cu121.html"
pip install -e '.[inference]'
./patching/hydra
pip install 'huggingface-hub[cli]<1.0'
hf download facebook/sam-3d-objects --local-dir "$BF_MODELS/sam-3d-objects" --max-workers 1
```

使用上游[安装说明](https://github.com/facebookresearch/sam-3d-objects/blob/01417d16fb5cc762a60f370c1bf7f59d603ddfaf/doc/setup.md)
中该固定版本的环境；可用 conda 替代 mamba。需要编译 CUDA/PyTorch3D 的主机请保留官方依赖版本。
先在官方模型页获得权重访问权限。
`models.sam3d.path` 指向包含 `checkpoints/pipeline.yaml` 的父目录，
`models.sam3d.python` 是此 conda 环境解释器；`sources.sam3d` 是源码根目录。
本仓库带网格/相机坐标转换、纹理烘焙与资产注册桥接代码。

## Depth Anything V2（可选 CPU 相对深度）

```bash
git clone https://github.com/DepthAnything/Depth-Anything-V2.git "$BF_MODELS/depth-source"
git -C "$BF_MODELS/depth-source" checkout a561b849ebae10a6f5ef49e26c83cbbcd36c71bf
python3.11 -m venv "$BF_MODELS/depth-env"
"$BF_MODELS/depth-env/bin/pip" install torch torchvision --index-url https://download.pytorch.org/whl/cpu
"$BF_MODELS/depth-env/bin/pip" install -r "$BF_MODELS/depth-source/requirements.txt" huggingface_hub
"$BF_MODELS/depth-env/bin/hf" download depth-anything/Depth-Anything-V2-Small --local-dir "$BF_MODELS/depth-anything"
```

设置 `models.depth_anything.python`、指向 `depth_anything_v2_vits.pth` 的完整 `path`，
以及 `sources.depth_anything`。该输出为相对深度，不能充当米制深度 GT；
真实场景米制 GT 使用 Isaac 仿真记录。
