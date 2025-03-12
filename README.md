# Running RL on Two 8xH100 SF Compute Nodes

0. You need to create an SF compute account, put money on it, and install SF compute on your local machine.

1. Clone this repository and cd into it.
```bash
git clone https://github.com/astOwOlfo/SFComputeRL.git
cd SFComputeRL
```

3. Buy an SF compute cluster (in this example, 16 gpus for 2 hours at $1/gpu/hour).
```bash
$ sf buy -n 16 -s now -d 2hr -p 1
```
Alternatively, buy a 16 gpu cluster using the graphic interface [here](https://sfcompute.com/dashboard).

2. Setup the cluster
```bash
python setup.py --kubernetes-config-filename <single_ssh_pod.yaml or double_ssh_pod.yaml> --remote-docker-host <ubuntu@lambda_lab_ip> --weights-and-biases-api-key <token>
```
- `setup.py` will print a ray status at the end. Check that it shows 0/16 gpus.

3. Run RL
```bash
ssh -p 2222 root@localhost
cd /app/swe_bench_rl/
apt install -y nano
nano run_rl.sh # then modify the RL settings to be what you want
./run_rl.sh # run the RL run
```
