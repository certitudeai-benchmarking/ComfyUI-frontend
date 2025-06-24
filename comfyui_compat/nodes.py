import hashlib
import importlib
import json
import logging
import os
import random
import sys
import time
import traceback

import numpy as np
import torch
from comfy import model_management
from comfy.cli_args import args
from folder_paths import (
    exists_annotated_filepath,
    get_annotated_filepath,
    get_folder_paths,
    get_input_directory,
    get_output_directory,
    get_save_image_path,
)
from node_helpers import pillow
from PIL import Image, ImageOps, ImageSequence
from PIL.PngImagePlugin import PngInfo


def before_node_execution():
    model_management.throw_exception_if_processing_interrupted()


def interrupt_processing(value=True):
    model_management.interrupt_current_processing(value)


MAX_RESOLUTION = 16384


class SaveImage:
    def __init__(self):
        self.output_dir = get_output_directory()
        self.type = "output"
        self.prefix_append = ""
        self.compress_level = 4

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "The images to save."}),
                "filename_prefix": (
                    "STRING",
                    {
                        "default": "ComfyUI",
                        "tooltip": "The prefix for the file to save. This may include formatting information such as %date:yyyy-MM-dd% or %Empty Latent Image.width% to include values from nodes.",
                    },
                ),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ()
    FUNCTION = "save_images"

    OUTPUT_NODE = True

    CATEGORY = "Tools"
    DESCRIPTION = "Saves the input images to your ComfyUI output directory."

    def save_images(
        self,
        images,
        filename_prefix="ComfyUI",
        prompt=None,
        extra_pnginfo=None,
        job_id=None,
    ):
        filename_prefix += self.prefix_append
        self.output_dir = get_output_directory(job_id)
        full_output_folder, filename, counter, subfolder, filename_prefix = (
            get_save_image_path(
                filename_prefix, self.output_dir, images[0].shape[1], images[0].shape[0]
            )
        )
        results = list()
        for batch_number, image in enumerate(images):
            if isinstance(image, torch.Tensor):
                image = image.cpu().numpy()

            i = 255.0 * image
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
            metadata = None
            if not args.disable_metadata:
                metadata = PngInfo()
                if prompt is not None:
                    metadata.add_text("prompt", json.dumps(prompt))
                if extra_pnginfo is not None:
                    for x in extra_pnginfo:
                        metadata.add_text(x, json.dumps(extra_pnginfo[x]))

            filename_with_batch_num = filename.replace("%batch_num%", str(batch_number))
            file = f"{filename_with_batch_num}_{counter:05}_.png"
            img.save(
                os.path.join(full_output_folder, file),
                pnginfo=metadata,
                compress_level=self.compress_level,
            )
            results.append(
                {"filename": file, "subfolder": subfolder, "type": self.type}
            )
            counter += 1

        return {"ui": {"images": results}}


class PreviewImage(SaveImage):
    def __init__(self):
        self.output_dir = get_output_directory()
        self.type = "output"
        self.prefix_append = "_temp_" + "".join(
            random.choice("abcdefghijklmnopqrstupvxyz") for x in range(5)
        )
        print(f"PreviewImage prefix_append: {self.prefix_append}")

        self.compress_level = 1
        print(f"PreviewImage compress level: {self.compress_level}")

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images": ("IMAGE",),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }


class LoadImage:
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = get_input_directory()
        print(f"LoadImage input_dir :  {input_dir}")
        files = [
            f
            for f in os.listdir(input_dir)
            if os.path.isfile(os.path.join(input_dir, f))
        ]
        sorted_files = sorted(files)
        files_with_none = [None] + sorted_files
        return {
            "required": {"image": (files_with_none, {"image_upload": True})},
        }

    CATEGORY = "Tools"
    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "load_image"

    def load_image(self, image, job_id: str = None):
        if image is None:
            return (None, None)

        image_path = get_annotated_filepath(image)
        img = pillow(Image.open, image_path)
        output_images = []
        output_masks = []
        w, h = None, None
        excluded_formats = ["MPO"]

        for i in ImageSequence.Iterator(img):
            i = pillow(ImageOps.exif_transpose, i)

            if i.mode == "I":
                i = i.point(lambda i_val: i_val * (1 / 255))
            image_frame = i.convert("RGB")

            if len(output_images) == 0:
                w, h = image_frame.size

            if image_frame.size[0] != w or image_frame.size[1] != h:
                continue

            image_arr = np.array(image_frame).astype(np.float32) / 255.0

            if "A" in i.getbands():
                mask = np.array(i.getchannel("A")).astype(np.float32) / 255.0
                mask = 1.0 - mask
            else:
                mask = np.zeros((64, 64), dtype=np.float32)
            output_images.append(image_arr)
            output_masks.append(mask[np.newaxis, ...])

        if (
            len(output_images) > 1
            and getattr(img, "format", None) not in excluded_formats
        ):
            output_image = np.concatenate(output_images, axis=0)
            output_mask = np.concatenate(output_masks, axis=0)
        else:
            output_image = output_images[0]
            output_mask = output_masks[0]

        output_image = np.expand_dims(output_image, axis=0)
        output_mask = np.expand_dims(output_mask, axis=0)

        return (output_image, output_mask)

    @classmethod
    def IS_CHANGED(cls, image):
        if image is None:
            return None

        image_path = get_annotated_filepath(image)
        m = hashlib.sha256()
        with open(image_path, "rb") as f:
            m.update(f.read())
        return m.digest().hex()

    @classmethod
    def VALIDATE_INPUTS(cls, image):
        if image is None:
            return True

        if not exists_annotated_filepath(image):
            return "Invalid image file: {}".format(image)
        return True


class LoadText:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "text": (
                    "STRING",
                    {
                        "placeholder": "Healing shadows where tears still lie",
                        "multiline": False,
                        "dynamicPrompts": False,
                        "tooltip": "The text to be encoded.",
                    },
                )
            }
        }

    RETURN_TYPES = ("TEXT",)
    OUTPUT_TOOLTIPS = ("The loaded text.",)
    FUNCTION = "encode"
    CATEGORY = "Tools"
    DESCRIPTION = "Loads a text string that can be used as input for other nodes."

    def encode(self, text):
        return (text,)


class LoadTextPath:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "text_path": (
                    "STRING",
                    {"multiline": False, "tooltip": "Enter the path to your text file"},
                ),
            },
        }

    CATEGORY = "Tools"
    RETURN_TYPES = ("TEXT",)
    FUNCTION = "load_text"
    OUTPUT_TOOLTIPS = ("The loaded text content.",)
    DESCRIPTION = "Loads text content from a specified file path."

    def load_text(self, text_path):
        try:
            with open(text_path, "r", encoding="utf-8") as f:
                content = f.read()
            return (content,)
        except UnicodeDecodeError:
            # Try with a different encoding if UTF-8 fails
            with open(text_path, "r", encoding="latin-1") as f:
                content = f.read()
            return (content,)
        except FileNotFoundError:
            raise FileNotFoundError(f"Could not find text file at path: {text_path}")
        except Exception as e:
            raise Exception(f"Error loading text file: {str(e)}")

    @classmethod
    def IS_CHANGED(s, text_path):
        try:
            m = hashlib.sha256()
            with open(text_path, "rb") as f:
                m.update(f.read())
            return m.digest().hex()
        except:
            # If file doesn't exist or can't be read, return a unique value
            return str(time.time())

    @classmethod
    def VALIDATE_INPUTS(s, text_path):
        if not os.path.exists(text_path):
            return f"Invalid text file path: {text_path}"
        if not os.path.isfile(text_path):
            return f"Path is not a file: {text_path}"
        return True


NODE_CLASS_MAPPINGS = {
    "SaveImage": SaveImage,
    "PreviewImage": PreviewImage,
    "LoadImage": LoadImage,
    "LoadText": LoadText,
    "LoadTextPath": LoadTextPath,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SaveImage": "Save Image",
    "PreviewImage": "Preview Image",
    "LoadImage": "Load Image",
    "LoadText": "Load Text",
    "LoadTextPath": "Load Text Path",
}

EXTENSION_WEB_DIRS = {}


def get_module_name(module_path: str) -> str:
    """
    Returns the module name based on the given module path.
    Examples:
        get_module_name("C:/Users/username/ComfyUI/custom_nodes/my_custom_node.py") -> "my_custom_node"
        get_module_name("C:/Users/username/ComfyUI/custom_nodes/my_custom_node") -> "my_custom_node"
        get_module_name("C:/Users/username/ComfyUI/custom_nodes/my_custom_node/") -> "my_custom_node"
        get_module_name("C:/Users/username/ComfyUI/custom_nodes/my_custom_node/__init__.py") -> "my_custom_node"
        get_module_name("C:/Users/username/ComfyUI/custom_nodes/my_custom_node/__init__") -> "my_custom_node"
        get_module_name("C:/Users/username/ComfyUI/custom_nodes/my_custom_node/__init__/") -> "my_custom_node"
        get_module_name("C:/Users/username/ComfyUI/custom_nodes/my_custom_node.disabled") -> "custom_nodes
    Args:
        module_path (str): The path of the module.
    Returns:
        str: The module name.
    """
    base_path = os.path.basename(module_path)
    if os.path.isfile(module_path):
        base_path = os.path.splitext(base_path)[0]
    return base_path


def load_custom_node(
    module_path: str, ignore=set(), module_parent="custom_nodes"
) -> bool:
    module_name = os.path.basename(module_path)
    if os.path.isfile(module_path):
        sp = os.path.splitext(module_path)
        module_name = sp[0]
    try:
        logging.debug("Trying to load custom node {}".format(module_path))
        if os.path.isfile(module_path):
            module_spec = importlib.util.spec_from_file_location(
                module_name, module_path
            )
            module_dir = os.path.split(module_path)[0]
        else:
            module_spec = importlib.util.spec_from_file_location(
                module_name, os.path.join(module_path, "__init__.py")
            )
            module_dir = module_path

        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        module_spec.loader.exec_module(module)

        if (
            hasattr(module, "WEB_DIRECTORY")
            and getattr(module, "WEB_DIRECTORY") is not None
        ):
            web_dir = os.path.abspath(
                os.path.join(module_dir, getattr(module, "WEB_DIRECTORY"))
            )
            if os.path.isdir(web_dir):
                EXTENSION_WEB_DIRS[module_name] = web_dir

        if (
            hasattr(module, "NODE_CLASS_MAPPINGS")
            and getattr(module, "NODE_CLASS_MAPPINGS") is not None
        ):
            for name, node_cls in module.NODE_CLASS_MAPPINGS.items():
                if name not in ignore:
                    NODE_CLASS_MAPPINGS[name] = node_cls
                    node_cls.RELATIVE_PYTHON_MODULE = "{}.{}".format(
                        module_parent, get_module_name(module_path)
                    )
            if (
                hasattr(module, "NODE_DISPLAY_NAME_MAPPINGS")
                and getattr(module, "NODE_DISPLAY_NAME_MAPPINGS") is not None
            ):
                NODE_DISPLAY_NAME_MAPPINGS.update(module.NODE_DISPLAY_NAME_MAPPINGS)
            return True
        else:
            logging.warning(
                f"Skip {module_path} module for custom nodes due to the lack of NODE_CLASS_MAPPINGS."
            )
            return False
    except Exception as e:
        logging.warning(traceback.format_exc())
        logging.warning(f"Cannot import {module_path} module for custom nodes: {e}")
        return False


def init_external_custom_nodes():
    """
    Initializes the external custom nodes.

    This function loads custom nodes from the specified folder paths and imports them into the application.
    It measures the import times for each custom node and logs the results.

    Returns:
        None
    """
    base_node_names = set(NODE_CLASS_MAPPINGS.keys())
    node_paths = get_folder_paths("custom_nodes")
    node_import_times = []
    for custom_node_path in node_paths:
        possible_modules = os.listdir(os.path.realpath(custom_node_path))
        if "__pycache__" in possible_modules:
            possible_modules.remove("__pycache__")

        for possible_module in possible_modules:
            module_path = os.path.join(custom_node_path, possible_module)
            if (
                os.path.isfile(module_path)
                and os.path.splitext(module_path)[1] != ".py"
            ):
                continue
            if module_path.endswith(".disabled"):
                continue
            time_before = time.perf_counter()
            success = load_custom_node(
                module_path, base_node_names, module_parent="custom_nodes"
            )
            node_import_times.append(
                (time.perf_counter() - time_before, module_path, success)
            )

    if len(node_import_times) > 0:
        logging.info("\nImport times for custom nodes:")
        for n in sorted(node_import_times):
            if n[2]:
                import_message = ""
            else:
                import_message = " (IMPORT FAILED)"
            logging.info("{:6.1f} seconds{}: {}".format(n[0], import_message, n[1]))
        logging.info("")


def init_builtin_extra_nodes():
    """
    Initializes the built-in extra nodes in ComfyUI.

    This function loads the extra node files located in the "comfy_extras" directory and imports them into ComfyUI.
    If any of the extra node files fail to import, a warning message is logged.

    Returns:
        None
    """
    extras_dir = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "comfy_extras"
    )
    extras_files = [
        "nodes_latent.py",
        "nodes_hypernetwork.py",
        "nodes_upscale_model.py",
        "nodes_post_processing.py",
        "nodes_mask.py",
        "nodes_compositing.py",
        "nodes_rebatch.py",
        "nodes_model_merging.py",
        "nodes_tomesd.py",
        "nodes_clip_sdxl.py",
        "nodes_canny.py",
        "nodes_freelunch.py",
        "nodes_custom_sampler.py",
        "nodes_hypertile.py",
        "nodes_model_advanced.py",
        "nodes_model_downscale.py",
        "nodes_images.py",
        "nodes_video_model.py",
        "nodes_sag.py",
        "nodes_perpneg.py",
        "nodes_stable3d.py",
        "nodes_sdupscale.py",
        "nodes_photomaker.py",
        "nodes_cond.py",
        "nodes_morphology.py",
        "nodes_stable_cascade.py",
        "nodes_differential_diffusion.py",
        "nodes_ip2p.py",
        "nodes_model_merging_model_specific.py",
        "nodes_pag.py",
        "nodes_align_your_steps.py",
        "nodes_attention_multiply.py",
        "nodes_advanced_samplers.py",
        "nodes_webcam.py",
        "nodes_audio.py",
        "nodes_sd3.py",
        "nodes_gits.py",
        "nodes_controlnet.py",
        "nodes_hunyuan.py",
        "nodes_flux.py",
    ]

    import_failed = []
    for node_file in extras_files:
        if not load_custom_node(
            os.path.join(extras_dir, node_file), module_parent="comfy_extras"
        ):
            import_failed.append(node_file)

    return import_failed


def init_extra_nodes(init_custom_nodes=True):
    if init_custom_nodes:
        init_external_custom_nodes()
    else:
        logging.info("Skipping loading of custom nodes")
