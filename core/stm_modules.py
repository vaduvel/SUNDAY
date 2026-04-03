"""⚡ STM Modules - Semantic Transformation Modules

Based on G0DM0D3's STM:
- Normalize AI outputs in real-time
- Remove hedge words, preambles
- Add exploration prompts
"""

import re
from typing import Callable


class STMModules:
    """Semantic Transformation Modules for output normalization."""

    def __init__(self):
        self.hedge_words = [
            "i think",
            "i believe",
            "perhaps",
            "maybe",
            "might",
            "could be",
            "probably",
            "likely",
            "possibly",
            "seems",
            "appears",
            "it seems",
            "as far as i know",
            "to my knowledge",
            "i'm not sure",
            "i'm not certain",
        ]

        self.preamble_phrases = [
            "as an ai language model",
            "as a language model",
            "i'm sorry but",
            "i cannot",
            "i'm unable to",
            "i don't have the ability",
            "however, i'm not able to",
            "i'm not in a position to",
        ]

        self.filler_phrases = [
            "sure!",
            "of course!",
            "certainly!",
            "absolutely!",
            "no problem!",
            "happy to help!",
            "great question!",
            "good question!",
            "interesting!",
            "that's a great question",
        ]

    def hedge_reducer(self, text: str) -> str:
        """Remove hedge words and make output more direct."""
        result = text.lower()

        for hedge in self.hedge_words:
            result = re.sub(
                r"\b" + re.escape(hedge) + r"\b", "", result, flags=re.IGNORECASE
            )

        # Clean up extra spaces
        result = re.sub(r"\s+", " ", result).strip()

        # Capitalize first letter if it was removed
        if result and not result[0].isupper():
            result = result[0].upper() + result[1:]

        return result or text

    def direct_mode(self, text: str) -> str:
        """Remove preambles and filler phrases."""
        result = text.lower()

        # Remove preamble phrases
        for preamble in self.preamble_phrases:
            if preamble in result:
                result = result.replace(preamble, "")

        # Remove filler phrases at start
        for filler in self.filler_phrases:
            if result.startswith(filler):
                result = result[len(filler) :].strip()

        # Clean up
        result = re.sub(r"\s+", " ", result).strip()

        return result or text

    def curiosity_bias(self, text: str) -> str:
        """Add exploration prompts to encourage curiosity."""
        # Only add if response is short/medium and doesn't already have questions
        if len(text) > 500 or "?" in text:
            return text

        additions = [
            "\n\n💡 Curious about more? Ask me to elaborate!",
            "\n\n🔍 Want me to dig deeper into this?",
            "\n\n✨ Would you like to explore this further?",
        ]

        return text + additions[0]

    def remove_thought_tags(self, text: str) -> str:
        """Remove <thought> tags from output."""
        # Remove thought blocks
        text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
        text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL)
        text = re.sub(r"\(thinking.*?\)", "", text, flags=re.DOTALL)
        return text

    def clean_json_blocks(self, text: str) -> str:
        """Clean up JSON/code blocks."""
        # Remove empty code blocks
        text = re.sub(r"```\w*\n*```", "", text)

        # Clean up excessive newlines
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text

    def apply_all(self, text: str, mode: str = "direct") -> str:
        """Apply all transformations based on mode."""
        # Always remove thought tags
        text = self.remove_thought_tags(text)

        if mode == "hedge":
            text = self.hedge_reducer(text)
        elif mode == "direct":
            text = self.direct_mode(text)
            text = self.clean_json_blocks(text)
        elif mode == "curious":
            text = self.curiosity_bias(text)
        elif mode == "minimal":
            text = self.hedge_reducer(text)
            text = self.direct_mode(text)
        elif mode == "full":
            text = self.hedge_reducer(text)
            text = self.direct_mode(text)
            text = self.clean_json_blocks(text)

        return text.strip()


# Singleton
_stm = None


def get_stm() -> STMModules:
    global _stm
    if _stm is None:
        _stm = STMModules()
    return _stm


# Test
if __name__ == "__main__":
    stm = STMModules()

    test_text = """
    <thought>I should analyze this request carefully.</thought>
    Sure! I'd be happy to help you with that. I think this might be a good approach, 
    but maybe we should consider other options. As an AI language model, I can provide 
    some guidance, though I'm not entirely certain about the specifics.
    
    Here's the code:
    ```python
    def hello():
        pass
    ```
    
    Probably this works!
    """

    print("=== Original ===")
    print(test_text)
    print()

    print("=== Direct Mode ===")
    print(stm.apply_all(test_text, "direct"))
    print()

    print("=== Minimal Mode ===")
    print(stm.apply_all(test_text, "minimal"))
