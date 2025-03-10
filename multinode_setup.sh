set -x

# get cluster name
CLUSTER_NAME=$(sf clusters list | grep "^Name" | awk '{print $2}')

# add user named vlad to cluster
sf clusters users add --cluster $CLUSTER_NAME --user vlad

# start pods
kubectl apply -f double_ssh_pod.yaml
read -p "Wait until the output of 'kubectl get pods' shows that ssh-pod-8gpu-1 and ssh-pod-8gpu-2 are both running, then press enter. Do not press enter before."

# setup sshing into both nodes
kubectl port-forward pod/ssh-pod-8gpu-1 2222:22 & sleep 1
kubectl port-forward pod/ssh-pod-8gpu-2 2223:22 & sleep 1

# clear some ssh stateful stuff that remains from the previous times this script was run
ssh-keygen -f "/home/user/.ssh/known_hosts" -R "[localhost]:2222"
ssh-keygen -f "/home/user/.ssh/known_hosts" -R "[localhost]:2223"

# for port in 2222 2223 # on both pods
# do
#     # install uv then install ray
#     ssh -o StrictHostKeyChecking=no -p $port root@localhost 'apt update; apt install -y curl; curl -LsSf https://astral.sh/uv/install.sh | sh; source $HOME/.local/bin/env; uv venv; uv pip install ray'
# done

for port in 2222 2223 # on both pods
do
    # install cursed things
    ssh -o StrictHostKeyChecking=no -p $port root@localhost "apt install -y libnccl2=2.21.5-1+cuda12.4 libnccl-dev=2.21.5-1+cuda12.4; export PATH=/usr/local/nvidia/bin:/usr/local/cuda/bin:$PATH"

    # install the swe_bench_rl repo
    ssh -o StrictHostKeyChecking=no -p $port root@localhost 'source $HOME/.local/bin/env; cd /app/; git clone https://github.com/astOwOlfo/swe_bench_rl.git --branch sf-compute; cd swe_bench_rl; echo "WANDB_API_KEY=95a39bca10d467330fa2726d53596dd8f1556d9d" > .env; uv venv; uv pip install setuptools psutil; timeout 60 ./installation.sh || ./installation.sh'

    # install cursed things
    ssh -o StrictHostKeyChecking=no -p $port root@localhost 'source $HOME/.local/bin/env; cd /app/swe_bench_rl/; uv pip install cupy-cuda12x --no-build-isolation'
    # ssh -o StrictHostKeyChecking=no -p $port root@localhost 'source $HOME/.local/bin/env; cd /app/swe_bench_rl/; uv pip install cupy-cuda12x --no-build-isolation; uv run python -m cupyx.tools.install_library --cuda 12.x --library cutensor; uv pip install cupy-cuda12x --no-build-isolation --reinstall'
done

# start ray on first node
ssh -o StrictHostKeyChecking=no -p 2222 root@localhost 'source $HOME/.local/bin/env; cd /app/swe_bench_rl/; uv run ray stop; uv run ray start --head' | tee temp.txt
RAY_ADDRESS=$(grep -o "ray start --address='[0-9.]\+:[0-9]\+'" temp.txt | sed "s/ray start --address='\([0-9.]\+:[0-9]\+\)'/\1/")
echo ray address is $RAY_ADDRESS

ssh -o StrictHostKeyChecking=no -p 2222 root@localhost "echo export RAY_ADDRESS=$RAY_ADDRESS >> .bashrc"
ssh -o StrictHostKeyChecking=no -p 2223 root@localhost "echo export RAY_ADDRESS=$RAY_ADDRESS >> .bashrc"

# start ray on second node
ssh -o StrictHostKeyChecking=no -p 2223 root@localhost 'source $HOME/.local/bin/env; cd /app/swe_bench_rl/; uv run ray stop; uv run ray start --address='$RAY_ADDRESS

echo '=== ray status on first cluster ==='
ssh -o StrictHostKeyChecking=no -p 2222 root@localhost 'source $HOME/.local/bin/env; cd /app/swe_bench_rl/; uv run ray status'
echo '=== ray status on second cluster ==='
ssh -o StrictHostKeyChecking=no -p 2223 root@localhost 'source $HOME/.local/bin/env; cd /app/swe_bench_rl/; uv run ray status'

# things i did on both machines:
# apt install -y libgloo-dev
