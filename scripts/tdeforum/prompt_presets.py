"""Visionary / psychedelic starting prompts for the Prompts page "Prompt Preset" menu.

Picking one writes it into the COMP's prompt_seq table (beat | prompt | xfade) and switches
Prompt Source to the sequence; the rows it replaced are kept and come back when you pick None.
The global Negative Prompt (Globals page) still applies. Written for a photoreal LCM checkpoint:
concrete materials and light, a few strong nouns, no long artist lists.
"""

NONE = "none"


class PromptPreset(object):
    __slots__ = ("id", "label", "rows")

    def __init__(self, id, label, rows):
        self.id, self.label, self.rows = id, label, rows


def _one(prompt):
    return [("0", prompt, "")]


PRESETS = [
    PromptPreset("fractal_temple", "Fractal temple", _one(
        "vast fractal temple of iridescent glass and liquid gold, infinite recursive arches, sacred geometry, "
        "volumetric god rays through bioluminescent mist, hyperdetailed, cinematic lighting")),
    PromptPreset("mycelial_cosmos", "Mycelial cosmos", _one(
        "glowing mycelium network spanning a cosmic nebula, bioluminescent fungi, drifting spores like tiny "
        "galaxies, deep teal and magenta light, macro photography, ethereal, hyperdetailed")),
    PromptPreset("cosmic_eye", "Eye of the cosmos", _one(
        "colossal cosmic eye made of swirling galaxies, iris of nebula clouds, concentric rings of light, "
        "sacred geometry halo, otherworldly, volumetric light, ultra detailed")),
    PromptPreset("haeckel_abyss", "Haeckel abyss", _one(
        "radiolarians and jellyfish in the style of Ernst Haeckel, translucent bioluminescent sea creatures, "
        "intricate radial symmetry, deep ocean glow, scientific illustration meets hyperrealism")),
    PromptPreset("chromatic_liquid", "Chromatic liquid", _one(
        "molten chrome and rainbow oil flowing into kaleidoscopic patterns, liquid metal ripples, thin-film "
        "interference colours, macro photography, studio lighting, hyperreal")),
    PromptPreset("astral_forest", "Astral forest", _one(
        "ancient forest of crystal trees under a violet aurora, glowing runes in the bark, floating motes of "
        "light, mystical fog, fantasy realism, highly detailed")),
    PromptPreset("hyperspace", "Hyperspace lattice", _one(
        "geometric hyperspace tunnel of shifting jewel-toned mosaics, self-transforming beings of light, "
        "impossible architecture, intricate interlocking patterns, vivid saturated colours, transcendental")),
    PromptPreset("living_mandala", "Living mandala", _one(
        "living mandala of flowers, feathers and gemstones unfolding endlessly, perfect radial symmetry, "
        "gold filigree on deep indigo, ornate, hyperdetailed")),
    PromptPreset("blake_vision", "Blake vision", _one(
        "visionary engraving in the style of William Blake and Gustave Dore, angels spiralling through radiant "
        "clouds, cosmic light, dramatic chiaroscuro, epic, intricate")),
    PromptPreset("neural_bloom", "Neural bloom", _one(
        "bioluminescent neural network blooming like coral, synapses firing light, electric blue and violet, "
        "microscopic universe, shallow depth of field, hyperdetailed")),
]

BY_ID = dict((p.id, p) for p in PRESETS)
NAMES = [NONE] + [p.id for p in PRESETS]
LABELS = ["None (keep prompt_seq)"] + [p.label for p in PRESETS]


def get(name):
    return BY_ID.get(str(name or "").strip())
