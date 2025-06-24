import os
import sys

# Prioritize the compatibility module over the original ComfyUI module
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), "ComfyUI"))

# Calling `import nodes` and `import comfyui_compat.nodes` will create two different modules
# in sys.modules, which makes certain global variables not shared between them.
#
# This workaround ensures that only the compatibility module is used.
#
# If any part of the ComfyUI codebase imports something not in the compatibility module,
# it will have to be imported from the original ComfyUI module instead. This is done by
# simply importing the original ComfyUI module in the compatibility module.
import nodes

sys.modules["comfyui_compat.nodes"] = sys.modules["nodes"]

import folder_paths

sys.modules["comfyui_compat.folder_paths"] = sys.modules["folder_paths"]
