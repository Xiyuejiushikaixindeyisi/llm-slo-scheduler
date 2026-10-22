#!/bin/bash
# g5 最终启动脚本（EXP_10.21 基线版）：单节点拉起本节点 P NM + D NM（双侧对称 HCCL env）。
# 结构 = 正本 steps/s4_1_launch/nm_launch_one.sh（P/D 双段）+ g4 setup_env 等价段（EXP_10.14
# run_2p2d_exp.sh:208-228 逐字，HCCL_IF_IP=$IP、NIC=enp67s0f5 三节点统一）。
# SLO_*/predictor 四变量仅以命令前缀进 P NM（非 export，不泄给 D）；D 保持纯净。
# TAG/IP 双替换（由 apply 脚本 sed）。
set -e
TAG=__TAG__; IP=__IP__
NAME=motor3p3d-zxy
LOGD=/mnt/esfs/zhangxiyue/qwen3.6-27b/FGJSQ_3P3D/EXP_10.20_MOTOR/04_stack_logs
CFG=/mnt/esfs/zhangxiyue/qwen3.6-27b/FGJSQ_3P3D/EXP_10.20_MOTOR/03_stack/config_sample.json
MC=/mnt/esfs/zhangxiyue/qwen3.6-27b/mooncake_exp_cluster49.json
MODEL=/mnt/esfs/zhangxiyue/qwen3.6-27b/FGJSQ_3P3D/code/predictor_pretrained/model.pkl
NIC=enp67s0f5
cat > /tmp/inside_nm_pd.sh <<I2
set -e
cd $LOGD
# ===== g4 setup_env 等价段（P/D 双侧对称）=====
export PYTHONHASHSEED=0
export HCCL_INTRA_ROCE_ENABLE=1
export HCCL_RDMA_TIMEOUT=17
export ASCEND_CONNECT_TIMEOUT=10000
export ASCEND_TRANSFER_TIMEOUT=10000
export VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS=12000
export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"
export HCCL_OP_EXPANSION_MODE="AIV"
export HCCL_BUFFSIZE=1024
export TASK_QUEUE_ENABLE=1
export HCCL_IF_IP="$IP"
export GLOO_SOCKET_IFNAME="$NIC"
export TP_SOCKET_IFNAME="$NIC"
export HCCL_SOCKET_IFNAME="$NIC"
export OMP_PROC_BIND=false
export OMP_NUM_THREADS=10
# ===== P NM（fgjsq/predictor env 以命令前缀注入，仅 P）=====
ROLE=prefill INDEX=0 POD_IP=$IP JOB_NAME=motor3p3d-zxy-p__TAG__ USER_CONFIG_PATH=$CFG \
MOONCAKE_CONFIG_PATH=$MC \
SLO_PATCH_ROLE=prefill ENABLE_BATCH_REPORTER=1 ENABLE_VLLM_TTFT_SLO_MS=0 \
SLO_PREDICTOR_MODEL_PATH=$MODEL \
  nohup python3 -m motor.node_manager.main > $LOGD/n${TAG}_nmp.log 2>&1 &
echo nmp_pid=\$!
sleep 8
# ===== D NM（无 fgjsq/predictor env）=====
ROLE=decode INDEX=0 POD_IP=$IP JOB_NAME=motor3p3d-zxy-d__TAG__ USER_CONFIG_PATH=$CFG \
MOONCAKE_CONFIG_PATH=$MC \
  nohup python3 -m motor.node_manager.main > $LOGD/n${TAG}_nmd.log 2>&1 &
echo nmd_pid=\$!
sleep 8
pgrep -f 'motor.node_manager.main' | wc -l
I2
docker cp /tmp/inside_nm_pd.sh $NAME:/tmp/inside_nm_pd.sh
docker exec $NAME bash /tmp/inside_nm_pd.sh
echo NODE_PD_DONE
