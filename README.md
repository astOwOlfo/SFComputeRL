# Running RL on Two 8xH100 SF Compute Nodes

0. You need to create an SF compute account, put money on it, and install SF compute on your local machine.

1. Clone this repository and cd into it.
```bash
git clone https://github.com/astOwOlfo/SFComputeRL.git
cd SFComputeRL
```

2. Install [uv](https://github.com/astral-sh/uv) if you don't already have it.
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

3. Buy an SF Compute cluster with the number of nodes you want.

**Recommended method:** Use [SF Compute's graphical interface](https://sfcompute.com/buy).

**Alternative method:** se their CLI interface ([instructions to install the CLI interface](https://sfcompute.com/dashboard)).
```bash
$ sf buy -n 16 -s now -d 2hr -p 1 # buy 16 gpus (2 nodes), get them right now (you can also schedule when you would like to have them), for 2 hours (this will be rounded to make the contract end on a time which's minutes are :00)
```

3. Setup the cluster
```bash
uv run setup.py --kubernetes-config-filename ssh_pod_<number of nodes you want>_nodes.yaml --github-repo JYudelson1/swe-tests [--github-username <username> --github-password-or-token <password-or-token>] [--remote-docker-host <username@ip_addres>] --weights-and-biases-api-key <token>
```
- If the github repo you want to clone is private (the one in the example is private), the github username and password should be provided and have the permissions to clone the repo.
- This will print a ray status at the end. Check that it shows 0/n gpus, where n is the number of gpus you bought.
- It will print all the commands and their (truncated) outputs. You shouldn't care about them unless something fails, in which case please ask me (Vladimir Ivanov) to fix it (please send me the output of `setup.py`).
-- It may print SSH security warnings. Ignore them.
- `--remote-docker-host` should be the username and ip of a machine into which you can SSH from the machine you are running setup.py from. It is required if you want to use Docker on the SF compute machines. The machine should be a virtual machine, **not** a docker machine. It should have docker already installed. I would recommend a reasonably good CPU, at least 32GB of RAM, and at least 1TB of disk space. The machine does not need to have a GPU. Renting the cheapest GPU machine available on Lambda Labs works well (you will be wasting a bit money because you're renting a GPU which won't be used).
-- Explanation of why we need this: SF Compute machines use Docker containers. It is annoying to run Docker containers within Docker containers (and might actually be impossible without enabling some permissions that I'm not sure SF Compute would let you enable). So instead, we run the docker server on a remote virtual machine, and only do API calls to it on the SF Compute machines. We do this by setting up docker in such a way that one can use it on the SF Compute machines as one would normally use it without any changes, and the calls to the virtual machine happen under the hood.
-- If you need to specify an identity file to SSH into the virtual machine, provide `--remote-docker-server-identity-file`.

After `setup.py` finishes running, it will print what commands one could use to ssh into each node.

3. Run RL
```bash
ssh -p 2222 root@localhost # or whichever command setup.py told you to use to ssh into the HEAD node

cd swe-tests

nano run_rl.sh # then modify the RL settings to be what you want
# /!\ !!! if you are using more than one node and run_rl.sh has lines which do `ray stop` and `ray start`, comment them !!! /!\

.swe-tests # run the RL run
```
