"""Versioned presentation only; equations, API keys, prices and physics stay fixed."""
import re

PROMPT_VERSION = 'synthetic-neural-v1'
INTRO = '''You are studying a synthetic neural system with 720 idealized binary neural
units, 20 auxiliary control inputs, and 20 binary readouts. This is an artificial,
deterministic, memoryless control environment, not a biological simulation.
Unit indices are interface addresses, not spatial coordinates. In a research
trial you set all 740 input bits and observe the 20 readout bits. Build eight
controllers that produce their assigned readout targets despite changing
external unit states, within the research and hardware budget. The rules below
define the complete interface and scoring contract.

Terminology: the 720 unit states are the shared inputs; their interface addresses
are shared ports. The 20 auxiliary control inputs are called private handles in
the API. Readouts are output bits, distinct from both kinds of input. Each
controller is installed on a separate copy of the same unknown system.'''


def family_prior(text):
    """Translate only declared F ontology; do not add or infer instance knowledge."""
    text = text.replace('Inter-material interface law', 'Interactions between functional modules')
    text = re.sub(r'\bmaterials\b', 'modules', text)
    text = re.sub(r'\bMaterials\b', 'Modules', text)
    text = re.sub(r'\bmaterial\b', 'module', text)
    text = re.sub(r'\bMaterial\b', 'Module', text)
    text = text.replace('manufactured copies', 'deployed system copies')
    return text
