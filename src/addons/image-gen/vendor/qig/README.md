# QIG source attribution

Source: https://github.com/platberlitz/sillytavern-image-gen
Pinned commit: 5915f096d899960b5013b759556098d310b2fc08 (manifest version 3.5.0).
License: MIT, retained verbatim in LICENSE.

Selected upstream libraries are copied verbatim. Workbench imports provider URL/payload/result helpers, image validation and materialization, A1111 URL normalization, ComfyUI workflow/polling/targeted cancellation, and prompt tag normalization. The upstream entry point, global initialization and UI are not included. Other retained exports are tree-shaken by esbuild. Workbench orchestration and native image persistence live outside this directory.
