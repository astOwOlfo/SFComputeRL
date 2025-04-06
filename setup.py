import socket
from shlex import quote
import subprocess
import os
import yaml
from argparse import ArgumentParser
from time import sleep
import re
from dataclasses import dataclass
from beartype import beartype

import optional as op


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
        print("here")

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

    assert (
        output.returncode == 0
    ), f"Command {command} failed with exit code {output.returncode}."
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
def add_user(
    username: str = "vlad", sf_compute_cluster_name: str | None = None
) -> None:
    cluster_name = op.unwrap_or(sf_compute_cluster_name, get_sf_compute_cluster_name())
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
    assert (
        pod.name in pod_to_status.keys()
    ), f"Pod {pod.name} not found in the output of 'kubectl get pods'."
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
        pod, f"apt install -y {' '.join(packages)}", truncate_output_to_length=256
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
def bash_command_that_comments_all_lines_containing(
    containing_what: str, file: str
) -> str:
    return f"sed -i 's/\\(.*{containing_what}.*\\)/#\\1/' {file}"


@beartype
def install_rl_repo(
    pod: Pod,
    weights_and_biases_api_key: str,
    github_repo: str,
    git_clone_directory: str,
    github_username: str | None,
    github_password_or_token: str | None,
) -> None:
    assert (github_username is None) == (github_password_or_token is None)
    if github_username is not None:
        github_repo_url = f"https://{github_username}:{github_password_or_token}@github.com/{github_repo}"
    else:
        github_repo_url = f"https://github.com/{github_repo}"

    ssh_run_command(
        pod,
        # "git clone https://github.com/astOwOlfo/simple_rl_experiments.git --branch sf-compute",
        # "rm -rf simple_rl_experiments; git clone https://github.com/emmyqin/simple_rl_experiments.git",
        f"rm -rf {git_clone_directory}; git clone {quote(github_repo_url)}",
        truncate_output_to_length=256,
    )
    ssh_run_command(
        pod,
        f'cd {git_clone_directory}; echo "WANDB_API_KEY={weights_and_biases_api_key}" > .env',
    )
    ssh_run_command(
        pod,
        f"cd {git_clone_directory}; source $HOME/.local/bin/env; uv venv",
        truncate_output_to_length=256,
    )
    ssh_run_command(
        pod,
        f"cd {git_clone_directory}; source $HOME/.local/bin/env; uv pip install setuptools psutil",
        truncate_output_to_length=256,
    )

    # temporary
    for excluded_package in ["swebench", "inspect_ai", "inspect-ai"]:
        ssh_run_command(
            pod,
            f"cd {git_clone_directory}; {bash_command_that_comments_all_lines_containing(containing_what=excluded_package, file='pyproject.toml')}",
        )

    ssh_run_command(
        pod,
        f"cd {git_clone_directory}; source $HOME/.local/bin/env; chmod +x installation.sh; timeout 60 ./installation.sh || ./installation.sh",
        truncate_output_to_length=256,
    )


@beartype
def install_cupy(pod: Pod, git_clone_directory: str) -> None:
    ssh_run_command(
        pod,
        f"cd {git_clone_directory}; source $HOME/.local/bin/env; uv pip install cupy-cuda12x --no-build-isolation",
        truncate_output_to_length=256,
    )


@beartype
def port_is_used(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


@beartype
def get_free_ports(how_many: int) -> list[int]:
    ports: list[int] = []
    candidate_port = 2222
    while len(ports) < how_many:
        if not port_is_used(candidate_port):
            ports.append(candidate_port)
        candidate_port += 1
    return ports


@beartype
def get_pods(config_filename: str) -> list[Pod]:
    # return [Pod(name="ssh-pod-8gpu-1", host_port=2224), Pod(name="ssh-pod-8gpu-2", host_port=2225)]

    with open(config_filename) as f:
        data = list(yaml.safe_load_all(f))

    host_ports = get_free_ports(how_many=len(data))

    return [
        Pod(name=d["metadata"]["name"], host_port=port)
        for d, port in zip(data, host_ports, strict=True)
    ]


@beartype
def start_ray_head_return_address(pod: Pod, git_clone_directory: str) -> str:
    ssh_run_command(
        pod,
        f"cd {git_clone_directory}; source $HOME/.local/bin/env; uv run ray stop",
        truncate_output_to_length=256,
    )
    output = ssh_run_command(
        pod,
        f"cd {git_clone_directory}; source $HOME/.local/bin/env; uv run ray stop; uv run ray start --head",
    )

    matches = re.findall(r"ray start --address='([0-9.]+:[0-9]+)'", output)
    assert len(matches) == 1, "Could not parse the output of ray start."
    address = matches[0]
    return address


@beartype
def start_and_connect_ray(
    pod: Pod, ray_head_address: str, git_clone_directory: str
) -> None:
    ssh_run_command(
        pod,
        f"cd {git_clone_directory}; source $HOME/.local/bin/env; uv run ray stop",
        truncate_output_to_length=256,
    )
    ssh_run_command(
        pod,
        f"cd {git_clone_directory}; source $HOME/.local/bin/env; uv run ray stop; uv run ray start --address={ray_head_address}",
    )


@beartype
def write_ray_address_to_bashrc(pod: Pod, address: str) -> None:
    ssh_run_command(pod, f"echo export RAY_ADDRESS={address} >> .bashrc")


@beartype
def print_ray_status(pod: Pod, ray_head_address: str, git_clone_directory: str) -> None:
    ssh_run_command(
        pod,
        f"cd {git_clone_directory}; source $HOME/.local/bin/env; uv run ray status --address={ray_head_address}",
    )


@beartype
def setup_ssh_connection(
    host_username_at_address: str, host_identity_file: str | None, guest_pods: list[Pod]
) -> None:
    ssh_run_command(
        guest_pods[0],
        "yes y | ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N '' -t ed25519",
    )

    private_ssh_key = ssh_run_command(guest_pods[0], "cat ~/.ssh/id_ed25519")
    public_ssh_key = ssh_run_command(guest_pods[0], "cat ~/.ssh/id_ed25519.pub")
    private_ssh_key = private_ssh_key.removesuffix("\n")
    public_ssh_key = public_ssh_key.removesuffix("\n")

    run_command(
        ["ssh", "-o", "StrictHostKeyChecking=no"]
        + (["-i", host_identity_file] if host_identity_file is not None else [])
        + [
            host_username_at_address,
            f"echo {public_ssh_key} >> ~/.ssh/authorized_keys",
        ]
    )

    for guest_pod in guest_pods[1:]:
        ssh_run_command(guest_pod, "mkdir -p ~/.ssh/")
        ssh_run_command(guest_pod, f"echo {public_ssh_key} > ~/.ssh/id_ed25519.pub")
        ssh_run_command(guest_pod, "rm -f ~/.ssh/id_ed25519")
        for line in private_ssh_key.splitlines():
            ssh_run_command(guest_pod, f"echo {line} >> ~/.ssh/id_ed25519")
        ssh_run_command(guest_pod, "chmod 600 ~/.ssh/id_ed25519")
        ssh_run_command(guest_pod, "chmod 600 ~/.ssh/id_ed25519.pub")

    for guest_pod in guest_pods:
        # this seems to always fail
        ssh_run_command(
            guest_pod,
            f"ssh -o StrictHostKeyChecking=no {host_username_at_address} echo",
        )


@beartype
def setup_remote_docker_server(
    host_username_at_address: str, host_identity_file: str | None, guest_pods: list[Pod]
) -> None:
    run_command(
        ["ssh", "-o", "StrictHostKeyChecking=no", host_username_at_address]
        + (["-i", host_identity_file] if host_identity_file is not None else [])
        + [
            "sudo usermod -aG docker $USER",
        ]
    )

    for guest_pod in guest_pods:
        ssh_run_command(
            guest_pod, "apt install -y docker.io", truncate_output_to_length=256
        )
        ssh_run_command(
            guest_pod,
            f'docker context create remote-server --docker "host=ssh://{host_username_at_address}"',
        )
        ssh_run_command(guest_pod, "docker context use remote-server")


@beartype
def main(
    kubernetes_config_filename: str,
    github_repo: str,
    github_username: str | None,
    github_password_or_token: str | None,
    remote_docker_host_username_at_address: str | None,
    remote_docker_host_identity_file: str | None,
    weights_and_biases_api_key: str,
    username_on_sf_compute_machine: str,
    sf_compute_cluster_name: str | None = None,
) -> None:
    add_user(
        username=username_on_sf_compute_machine,
        sf_compute_cluster_name=sf_compute_cluster_name,
    )

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

    git_clone_directory: str = quote(github_repo.split("/")[-1])

    for pod in pods:
        install_rl_repo(
            pod,
            weights_and_biases_api_key=weights_and_biases_api_key,
            github_repo=github_repo,
            git_clone_directory=git_clone_directory,
            github_username=github_username,
            github_password_or_token=github_password_or_token,
        )
        cleanup_ssh_keys(pod)
        install_nccl(pod)
        install_cupy(pod, git_clone_directory=git_clone_directory)
        apt_install(pod, ["nano", "nvtop", "tmux"])

    ray_head_address = start_ray_head_return_address(
        pods[0], git_clone_directory=git_clone_directory
    )
    for pod in pods[1:]:
        write_ray_address_to_bashrc(pod, address=ray_head_address)
        start_and_connect_ray(
            pod,
            ray_head_address=ray_head_address,
            git_clone_directory=git_clone_directory,
        )

    if remote_docker_host_username_at_address is not None:
        setup_ssh_connection(
            host_username_at_address=remote_docker_host_username_at_address,
            host_identity_file=remote_docker_host_identity_file,
            guest_pods=pods,
        )
        setup_remote_docker_server(
            host_username_at_address=remote_docker_host_username_at_address,
            host_identity_file=remote_docker_host_identity_file,
            guest_pods=pods,
        )

    for pod in pods:
        print(f"=== RAY STATUS ON POD {pod} ===")
        print_ray_status(
            pod,
            ray_head_address=ray_head_address,
            git_clone_directory=git_clone_directory,
        )

    print("=" * 100)
    print("SETUP FINISHED")
    print("=" * 100)
    for i_pod, pod in enumerate(pods):
        quoted_ssh_command: str = " ".join(
            quote(field) for field in get_ssh_command(pod)
        )
        print(f"SSH INTO {pod.name} BY RUNNING {quoted_ssh_command}", end="")
        if i_pod == 0:
            print(" (THIS IS THE HEAD POD - THE ONE YOU SHOULD BE RUNNING THINGS FROM)")
        else:
            print()


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--kubernetes-config-filename", type=str, required=True)
    parser.add_argument(
        "--github-repo",
        type=str,
        required=True,
        help="Github repository with the code to run RL experiments.",
    )
    parser.add_argument(
        "--github-username",
        type=str,
        help="Provide this and --github-password-or-token to be able to clone the repo if it is private.",
    )
    parser.add_argument("--github-password-or-token", type=str)
    parser.add_argument(
        "--remote-docker-host",
        type=str,
        help="username@ip one can ssh into that will be used for running docker remotely. If not provided, it will be impossible to run docker on the cluster. One has to use docker remotely because SF Compute machines are themselves docker containers and it is impossible to run docker containers within docker containers without having permissions that SF Compute doesn't give.",
    )
    parser.add_argument(
        "--remote-docker-host-identity-file",
        type=str,
        help="Same as the -i option of SSH.",
    )
    parser.add_argument("--weights-and-biases-api-key", type=str, required=True)
    parser.add_argument(
        "--username-on-sf-compute-machine",
        type=str,
        help="user for sf cluster",
        default="vlad",
    )
    parser.add_argument(
        "--cluster-name",
        type=str,
        required=False,
        help="sf compute cluster name",
        default=None,
    )
    args = parser.parse_args()

    main(
        kubernetes_config_filename=args.kubernetes_config_filename,
        github_repo=args.github_repo,
        github_username=args.github_username,
        github_password_or_token=args.github_password_or_token,
        remote_docker_host_username_at_address=args.remote_docker_host,
        remote_docker_host_identity_file=args.remote_docker_host_identity_file,
        weights_and_biases_api_key=args.weights_and_biases_api_key,
        username_on_sf_compute_machine=args.username_on_sf_compute_machine,
        sf_compute_cluster_name=args.cluster_name,
    )
