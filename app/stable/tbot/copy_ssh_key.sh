#!/bin/bash
# copy_ssh_key.sh

# Directory where SSH keys are stored
SSH_DIR="/home/tbot/.ssh"

# Find the private SSH key (filename starts with 'id' and doesn't have '.pub')
PRIVATE_KEY=$(find "$SSH_DIR" -type f -name 'id*' ! -name '*.pub' -print -quit)

# Check if a private key was found
if [[ -n "$PRIVATE_KEY" ]]; then
  # Copy the private key to the desired location
  cp "$PRIVATE_KEY" /home/tbot/.ssh/id_rsa
else
  echo "No private SSH key found."
  exit 1
fi
