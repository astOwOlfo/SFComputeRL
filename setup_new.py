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
def clone_and_install_rl_repo(
    pod: Pod,
    github_repo: str,
    github_branch: str | None,
    git_clone_directory: str,
    github_username: str | None,
    github_password_or_token: str | None,
) -> None:
    assert (github_username is None) == (github_password_or_token is None)
    if github_username is not None:
        github_repo_url = f"https://{github_username}:{github_password_or_token}@github.com/{github_repo}"
    else:
        github_repo_url = f"https://github.com/{github_repo}"

    if github_branch is not None:
        branch_argument = f" --branch {quote(github_branch)}"
    else:
        branch_argument = ""

    ssh_run_command(
        pod,
        f"rm -rf {git_clone_directory} && git clone {quote(github_repo_url)} {branch_argument}",
        truncate_output_to_length=256,
    )
    ssh_run_command(
        pod,
        f"cd {git_clone_directory} && uv venv && uv sync",
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
def main(
    kubernetes_config_filename: str,
    github_repo: str,
    github_branch: str | None,
    github_username: str | None,
    github_password_or_token: str | None,
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
    sleep(15)

    git_clone_directory: str = quote(github_repo.split("/")[-1])

    for pod in pods:
        clone_and_install_rl_repo(
            pod,
            github_repo=github_repo,
            github_branch=github_branch,
            git_clone_directory=git_clone_directory,
            github_username=github_username,
            github_password_or_token=github_password_or_token,
        )
        cleanup_ssh_keys(pod)

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
    parser.add_argument("--github-branch", help="Branch for --github-repo.")
    parser.add_argument(
        "--github-username",
        type=str,
        help="Provide this and --github-password-or-token to be able to clone the repo if it is private.",
    )
    parser.add_argument("--github-password-or-token", type=str)
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
        github_branch=args.github_branch,
        github_username=args.github_username,
        github_password_or_token=args.github_password_or_token,
        username_on_sf_compute_machine=args.username_on_sf_compute_machine,
        sf_compute_cluster_name=args.cluster_name,
    )
