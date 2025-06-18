#!/bin/bash

# Source the .env file if it exists
if [ -f .env ]; then
    source .env
fi

# Default values from .env or hardcoded fallbacks
NODES=${DEFAULT_NODES:-1}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --nodes)
      NODES="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Select the appropriate YAML file based on number of nodes
case $NODES in
  1)
    YAML_FILE="ssh_pod_1_nodes_old.yaml"
    ;;
  2)
    YAML_FILE="ssh_pod_2_nodes_old.yaml"
    ;;
  4)
    YAML_FILE="ssh_pod_4_nodes_old.yaml"
    ;;
  *)
    echo "Error: Unsupported number of nodes: $NODES"
    echo "Supported values are: 1, 2, 4"
    exit 1
    ;;
esac

# Execute the command
echo "Running: python setup_old.py --kubernetes-config-filename $YAML_FILE"
python setup_old.py --kubernetes-config-filename $YAML_FILE
