import shlex
import subprocess
import os
import yaml
from argparse import ArgumentParser
from time import sleep
import re
from dataclasses import dataclass
from beartype import beartype


@beartype
@dataclass(frozen=True)
class Pod:
    name: str
    host_port: int


@beartype
def truncate(string: str, max_length: int) -> str:
    if len(string) <= max_length:
        return string
    return string[: max_length // 2] + "\n[TRUNCATED]\n" + string[-max_length // 2 :]


@beartype
def run_command(
    command: list[str],
    background: bool = False,
    truncate_output_to_length: int | None = None,
    verbose: bool = True,
) -> str | None:
    if background:
        if verbose:
            print("=" * 100)
            print("RUNNING IN BACKGROUND:", command)
        subprocess.Popen(command)
        return None

    if verbose:
        print("=" * 100)
        print("RUNNING:", command)
    output = subprocess.run(command, capture_output=True, text=True)
    if verbose and output.stdout:
        print("=== STDOUT ===")
        if truncate_output_to_length is not None:
            print(truncate(output.stdout, truncate_output_to_length))
        else:
            print(output.stdout)
    if verbose and output.stderr:
        print("=== STDERR ===")
        if truncate_output_to_length is not None:
            print(truncate(output.stderr, truncate_output_to_length))
        else:
            print(output.stderr)

    assert output.returncode == 0, (
        f"Command {command} failed with exit code {output.returncode}."
    )
    return output.stdout


@beartype
def get_ssh_command(pod: Pod) -> list[str]:
    return [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-p",
        str(pod.host_port),
        "root@localhost",
    ]


@beartype
def ssh_run_command(
    pod: Pod, command: str, truncate_output_to_length: int | None = None
) -> str:
    return run_command(
        get_ssh_command(pod) + [command],
        truncate_output_to_length=truncate_output_to_length,
    )  # type: ignore


@beartype
def get_sf_compute_cluster_name() -> str:
    output: str = run_command(["sf", "clusters", "list"])  # type: ignore
    name = [
        line.strip().split()[1]
        for line in output.splitlines()
        if len(line.strip().split()) == 2 and line.strip().split()[0] == "Name"
    ]
    assert len(name) == 1, "Could not parse the output of 'sf clusters list'."
    return name[0]


@beartype
def add_user(username: str = "vlad") -> None:
    cluster_name = get_sf_compute_cluster_name()
    run_command(
        [
            "sf",
            "clusters",
            "users",
            "add",
            "--cluster",
            cluster_name,
            "--user",
            username,
        ]
    )


@beartype
def apply_kubernetes_pod_config(config_filename: str) -> None:
    run_command(["kubectl", "apply", "-f", config_filename])


@beartype
def pod_is_running(pod: Pod) -> bool:
    output: str = run_command(["kubectl", "get", "pods"], verbose=False)  # type: ignore
    pod_to_status: dict[str, str] = {
        line.split()[0]: line.split()[2]
        for line in output.splitlines()
        if line.strip() != ""
        and line.split() != ["NAME", "READY", "STATUS", "RESTARTS", "AGE"]
    }
    assert pod.name in pod_to_status.keys(), (
        f"Pod {pod.name} not found in the output of 'kubectl get pods'."
    )
    print(f"{pod_to_status=}")
    return pod_to_status[pod.name] == "Running"


@beartype
def forward_pod_ports_for_ssh(pod: Pod) -> None:
    run_command(
        ["kubectl", "port-forward", f"pod/{pod.name}", f"{pod.host_port}:22"],
        background=True,
    )


@beartype
def cleanup_ssh_keys(pod: Pod) -> None:
    run_command(
        [
            "ssh-keygen",
            "-f",
            os.path.expanduser("~/.ssh/known_hosts"),
            f"-R[localhost]:{pod.host_port}",
        ]
    )


@beartype
def apt_install(pod: Pod, packages: list[str]) -> None:
    ssh_run_command(
        pod, f"apt install {' '.join(packages)}", truncate_output_to_length=256
    )


@beartype
def install_nccl(pod: Pod) -> None:
    ssh_run_command(
        pod,
        "apt install -y libnccl2=2.21.5-1+cuda12.4 libnccl-dev=2.21.5-1+cuda12.4",
        truncate_output_to_length=256,
    )
    ssh_run_command(pod, "export PATH=/usr/local/nvidia/bin:/usr/local/cuda/bin:$PATH")


@beartype
def install_simple_rl_experiments(pod: Pod, weights_and_biases_api_key: str) -> None:
    ssh_run_command(
        pod,
        # "git clone https://github.com/astOwOlfo/simple_rl_experiments.git --branch sf-compute",
        "rm -rf simple_rl_experiments; git clone https://github.com/emmyqin/simple_rl_experiments.git",
        truncate_output_to_length=256,
    )
    ssh_run_command(
        pod,
        f'cd simple_rl_experiments/run-tests; echo "WANDB_API_KEY={weights_and_biases_api_key}" > .env',
    )
    ssh_run_command(
        pod,
        "cd simple_rl_experiments/run-tests; source $HOME/.local/bin/env; uv venv",
        truncate_output_to_length=256,
    )
    ssh_run_command(
        pod,
        "cd simple_rl_experiments/run-tests; source $HOME/.local/bin/env; uv pip install setuptools psutil",
        truncate_output_to_length=256,
    )
    ssh_run_command(
        pod,
        "cd simple_rl_experiments/run-tests; chmod +x installation.sh; timeout 60 ./installation.sh || ./installation.sh",
        truncate_output_to_length=256,
    )


@beartype
def install_cupy(pod: Pod) -> None:
    ssh_run_command(
        pod,
        "cd simple_rl_experiments/run-tests; source $HOME/.local/bin/env; uv pip install cupy-cuda12x --no-build-isolation",
        truncate_output_to_length=256,
    )


@beartype
def get_pods(config_filename: str) -> list[Pod]:
    # return [Pod(name="ssh-pod-8gpu-1", host_port=2224), Pod(name="ssh-pod-8gpu-2", host_port=2225)]

    with open(config_filename) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, list):
        data = [data]
    return [
        Pod(name=d["metadata"]["name"], host_port=2222 + i) for i, d in enumerate(data)
    ]


@beartype
def start_ray_head_return_address(pod: Pod) -> str:
    ssh_run_command(
        pod,
        "cd simple_rl_experiments/run-tests; source $HOME/.local/bin/env; uv run ray stop",
        truncate_output_to_length=256,
    )
    output = ssh_run_command(
        pod,
        "cd simple_rl_experiments/run-tests; source $HOME/.local/bin/env; uv run ray stop; uv run ray start --head",
    )

    matches = re.findall(r"ray start --address='([0-9.]+:[0-9]+)'", output)
    assert len(matches) == 1, "Could not parse the output of ray start."
    address = matches[0]
    return address


@beartype
def start_and_connect_ray(pod: Pod, ray_head_address: str) -> None:
    ssh_run_command(
        pod,
        "cd simple_rl_experiments/run-tests; source $HOME/.local/bin/env; uv run ray stop",
        truncate_output_to_length=256,
    )
    ssh_run_command(
        pod,
        f"cd simple_rl_experiments/run-tests; source $HOME/.local/bin/env; uv run ray stop; uv run ray start --address={ray_head_address}",
    )


@beartype
def write_ray_address_to_bashrc(pod: Pod, address: str) -> None:
    ssh_run_command(pod, f"echo export RAY_ADDRESS={address} >> .bashrc")


@beartype
def print_ray_status(pod: Pod, ray_head_address: str) -> None:
    ssh_run_command(
        pod,
        f"cd simple_rl_experiments/run-tests; source $HOME/.local/bin/env; uv run ray status --address={ray_head_address}",
    )


@beartype
def setup_ssh_connection(host_username_at_address: str, guest_pod: Pod) -> None:
    ssh_run_command(
        guest_pod, "yes y | ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N '' -t ed25519"
    )
    public_ssh_key = ssh_run_command(guest_pod, "cat ~/.ssh/id_ed25519.pub")
    public_ssh_key = public_ssh_key.removesuffix("\n")
    run_command(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            host_username_at_address,
            f"echo {public_ssh_key} >> ~/.ssh/authorized_keys",
        ]
    )

    # this seems to always fail
    ssh_run_command(
        guest_pod,
        # f"yes | ssh {host_username_at_address} echo"
        f"ssh -o StrictHostKeyChecking=no {host_username_at_address} echo"
    )  # make ssh not ask to type yes


@beartype
def setup_remote_docker_server(host_username_at_address: str, guest_pod: Pod) -> None:
    ssh_run_command(
        guest_pod, "apt install -y docker.io", truncate_output_to_length=256
    )
    run_command(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            host_username_at_address,
            "sudo usermod -aG docker $USER",
        ]
    )
    ssh_run_command(
        guest_pod,
        f'docker context create remote-server --docker "host=ssh://{host_username_at_address}"',
    )
    ssh_run_command(guest_pod, "docker context use remote-server")


@beartype
def main(
    kubernetes_config_filename: str,
    remote_docker_host_username_at_address: str | None,
    weights_and_biases_api_key: str,
) -> None:
    add_user()

    apply_kubernetes_pod_config(kubernetes_config_filename)

    pods = get_pods(kubernetes_config_filename)

    print("=== SETTING UP THE FOLLOWING PODS ===")
    for pod in pods:
        print(pod)

    print("=== WAITING UNTIL ALL PODS ARE RUNNING. THIS MIGHT TAKE A FEW MINUTES ===")
    for pod in pods:
        while not pod_is_running(pod):
            sleep(10)

    for pod in pods:
        forward_pod_ports_for_ssh(pod)
    sleep(5)

    for pod in pods:
        install_simple_rl_experiments(
            pod, weights_and_biases_api_key=weights_and_biases_api_key
        )
        cleanup_ssh_keys(pod)
        install_nccl(pod)
        install_cupy(pod)
        apt_install(pod, ["nano", "nvtop", "tmux"])

    ray_head_address = start_ray_head_return_address(pods[0])
    for pod in pods[1:]:
        write_ray_address_to_bashrc(pod, address=ray_head_address)
        start_and_connect_ray(pod, ray_head_address=ray_head_address)

    for pod in pods:
        print(f"=== RAY STATUS ON POD {pod} ===")
        print_ray_status(pod, ray_head_address=ray_head_address)

    if remote_docker_host_username_at_address is not None:
        for pod in pods:
            setup_ssh_connection(
                host_username_at_address=remote_docker_host_username_at_address,
                guest_pod=pod,
            )
            setup_remote_docker_server(
                host_username_at_address=remote_docker_host_username_at_address,
                guest_pod=pod,
            )

    print("=" * 100)
    print("SETUP FINISHED")
    print("=" * 100)
    for pod in pods:
        quoted_ssh_command: str = " ".join(
            shlex.quote(field) for field in get_ssh_command(pod)
        )
        print(f"SSH INTO {pod.name} BY RUNNING {quoted_ssh_command}")


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--kubernetes-config-filename", type=str, required=True)
    parser.add_argument(
        "--remote-docker-host",
        type=str,
        help="username@ip one can ssh into that will be used for running docker remotely. If not provided, it will be impossible to run docker on the cluster. One has to use docker remotely because SF Compute machines are themselves docker containers and it is impossible to run docker containers within docker containers without having permissions that SF Compute doesn't give.",
    )
    parser.add_argument("--weights-and-biases-api-key", type=str, required=True)
    args = parser.parse_args()

    main(
        kubernetes_config_filename=args.kubernetes_config_filename,
        remote_docker_host_username_at_address=args.remote_docker_host,
        weights_and_biases_api_key=args.weights_and_biases_api_key,
    )
