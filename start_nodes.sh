#!/bin/bash

# Source the .env file if it exists
if [ -f .env ]; then
    source .env
fi

# Default values from .env or hardcoded fallbacks
NODES=${DEFAULT_NODES:-1}
GITHUB_REPO=${DEFAULT_GITHUB_REPO:-""}
GITHUB_BRANCH=""
GITHUB_USERNAME=${DEFAULT_GITHUB_USERNAME:-""}
GITHUB_PASSWORD=${DEFAULT_GITHUB_PASSWORD:-""}
USERNAME=${DEFAULT_USERNAME:-"vlad"}
CLUSTER_NAME=${DEFAULT_CLUSTER_NAME:-""}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --nodes)
      NODES="$2"
      shift 2
      ;;
    --github-repo)
      GITHUB_REPO="$2"
      shift 2
      ;;
    --github-branch)
      GITHUB_BRANCH="$2"
      shift 2
      ;;
    --github-username)
      GITHUB_USERNAME="$2"
      shift 2
      ;;
    --github-password)
      GITHUB_PASSWORD="$2"
      shift 2
      ;;
    --username)
      USERNAME="$2"
      shift 2
      ;;
    --cluster-name)
      CLUSTER_NAME="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Validate required arguments
if [ -z "$GITHUB_REPO" ]; then
  echo "Error: --github-repo is required"
  exit 1
fi

# Select the appropriate YAML file based on number of nodes
case $NODES in
  1)
    YAML_FILE="ssh_pod_1_nodes.yaml"
    ;;
  2)
    YAML_FILE="ssh_pod_2_nodes.yaml"
    ;;
  4)
    YAML_FILE="ssh_pod_4_nodes.yaml"
    ;;
  *)
    echo "Error: Unsupported number of nodes: $NODES"
    echo "Supported values are: 1, 2, 4"
    exit 1
    ;;
esac

# Build the command
CMD="uv run setup.py --kubernetes-config-filename $YAML_FILE --github-repo $GITHUB_REPO"

# Add optional arguments if provided
if [ ! -z "$GITHUB_BRANCH" ]; then
  CMD="$CMD --github-branch $GITHUB_BRANCH"
fi

if [ ! -z "$GITHUB_USERNAME" ]; then
  CMD="$CMD --github-username $GITHUB_USERNAME"
fi

if [ ! -z "$GITHUB_PASSWORD" ]; then
  CMD="$CMD --github-password-or-token $GITHUB_PASSWORD"
fi

if [ ! -z "$USERNAME" ]; then
  CMD="$CMD --username-on-sf-compute-machine $USERNAME"
fi

if [ ! -z "$CLUSTER_NAME" ]; then
  CMD="$CMD --sf-compute-cluster-name $CLUSTER_NAME"
fi

# Execute the command
echo "Running: $CMD"
eval $CMD 