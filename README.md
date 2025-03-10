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
chmod +x multinode_setup.sh
./multinode_setup.sh
```
- Note that it will ask you to wait until the output of `kubectl get pods` shows that all pods are running. You should run this command repeatedly and wait until the output shows that the pods are running. It usually takes a few minutes.
- `./multinode_setup.sh` will print a ray status at the end. Check that it shows 0/16 gpus.

3. Run RL
```bash
ssh -p 2222 root@localhost
cd /app/swe_bench_rl/
apt install -y nano
nano run_rl.sh # then modify the RL settings to be what you want
./run_rl.sh # run the RL run
```
