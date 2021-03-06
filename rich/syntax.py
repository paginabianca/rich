import platform
import textwrap
from typing import Any, Dict, Optional, Set, Tuple, Union

from pygments.lexers import get_lexer_by_name, guess_lexer_for_filename
from pygments.styles import get_style_by_name
from pygments.style import Style as PygmentsStyle
from pygments.token import Token
from pygments.util import ClassNotFound

from .color import Color, parse_rgb_hex, blend_rgb
from .console import Console, ConsoleOptions, RenderResult, Segment, ConsoleRenderable
from .measure import Measurement
from .style import Style
from .text import Text
from ._tools import iter_first

WINDOWS = platform.system() == "Windows"
DEFAULT_THEME = "monokai"


class Syntax:
    """Construct a Syntax object to render syntax highlighted code.
    
    Args:
        code (str): Code to highlight.
        lexer_name (str): Lexer to use (see https://pygments.org/docs/lexers/)
        theme (str, optional): Color theme, aka Pygments style (see https://pygments.org/docs/styles/#getting-a-list-of-available-styles). Defaults to "emacs".
        dedent (bool, optional): Enable stripping of initial whitespace. Defaults to True.
        line_numbers (bool, optional): Enable rendering of line numbers. Defaults to False.
        start_line (int, optional): Starting number for line numbers. Defaults to 1.
        line_range (Tuple[int, int], optional): If given should be a tuple of the start and end line to render.
        highlight_lines (Set[int]): A set of line numbers to highlight.
        code_width: Width of code to render (not including line numbers), or ``None`` to use all available width.
        tab_size (int, optional): Size of tabs. Defaults to 4.
    """

    def __init__(
        self,
        code: str,
        lexer_name: str,
        *,
        theme: Union[str, PygmentsStyle] = DEFAULT_THEME,
        dedent: bool = False,
        line_numbers: bool = False,
        start_line: int = 1,
        line_range: Tuple[int, int] = None,
        highlight_lines: Set[int] = None,
        code_width: Optional[int] = None,
        tab_size: int = 4,
    ) -> None:
        self.code = code
        self.lexer_name = lexer_name
        self.dedent = dedent
        self.line_numbers = line_numbers
        self.start_line = start_line
        self.line_range = line_range
        self.highlight_lines = highlight_lines or set()
        self.code_width = code_width
        self.tab_size = tab_size

        self._style_cache: Dict[Any, Style] = {}
        if not isinstance(theme, str) and issubclass(theme, PygmentsStyle):
            self._pygments_style_class = theme
        else:
            try:
                self._pygments_style_class = get_style_by_name(theme)
            except ClassNotFound:
                self._pygments_style_class = get_style_by_name("default")
        self._background_color = self._pygments_style_class.background_color

    @classmethod
    def from_path(
        cls,
        path: str,
        encoding: str = "utf-8",
        theme: Union[str, PygmentsStyle] = DEFAULT_THEME,
        dedent: bool = True,
        line_numbers: bool = False,
        line_range: Tuple[int, int] = None,
        start_line: int = 1,
        highlight_lines: Set[int] = None,
        code_width: Optional[int] = None,
        tab_size: int = 4,
    ) -> "Syntax":
        """Construct a Syntax object from a file.
        
        Args:
            path (str): Path to file to highlight.
            encoding (str): Encoding of file.
            lexer_name (str): Lexer to use (see https://pygments.org/docs/lexers/)
            theme (str, optional): Color theme, aka Pygments style (see https://pygments.org/docs/styles/#getting-a-list-of-available-styles). Defaults to "emacs".
            dedent (bool, optional): Enable stripping of initial whitespace. Defaults to True.
            line_numbers (bool, optional): Enable rendering of line numbers. Defaults to False.
            start_line (int, optional): Starting number for line numbers. Defaults to 1.
            line_range (Tuple[int, int], optional): If given should be a tuple of the start and end line to render.
            highlight_lines (Set[int]): A set of line numbers to highlight.
            code_width: Width of code to render (not including line numbers), or ``None`` to use all available width.
            tab_size (int, optional): Size of tabs. Defaults to 4.

        Returns:
            [Syntax]: A Syntax object that may be printed to the console
        """
        with open(path, "rt", encoding=encoding) as code_file:
            code = code_file.read()
        try:
            lexer = guess_lexer_for_filename(path, code)
            lexer_name = lexer.name
        except ClassNotFound:
            lexer_name = "default"
        return cls(
            code,
            lexer_name,
            theme=theme,
            dedent=dedent,
            line_numbers=line_numbers,
            line_range=line_range,
            start_line=start_line,
            highlight_lines=highlight_lines,
            code_width=code_width,
        )

    def _get_theme_style(self, token_type) -> Style:
        if token_type in self._style_cache:
            style = self._style_cache[token_type]
        else:
            try:
                pygments_style = self._pygments_style_class.style_for_token(token_type)
            except KeyError:
                style = Style()
            else:
                color = pygments_style["color"]
                bgcolor = pygments_style["bgcolor"]
                style = Style(
                    color="#" + color if color else "#000000",
                    bgcolor="#" + bgcolor if bgcolor else self._background_color,
                    bold=pygments_style["bold"],
                    italic=pygments_style["italic"],
                    underline=pygments_style["underline"],
                )
            self._style_cache[token_type] = style

        return style

    def _get_default_style(self) -> Style:
        style = self._get_theme_style(Token.Text)
        style = style + Style(bgcolor=self._pygments_style_class.background_color)
        return style

    def _highlight(self, lexer_name: str) -> Text:
        default_style = self._get_default_style()
        try:
            lexer = get_lexer_by_name(lexer_name)
        except ClassNotFound:
            return Text(
                self.code, justify="left", style=default_style, tab_size=self.tab_size
            )
        text = Text(justify="left", style=default_style, tab_size=self.tab_size)
        append = text.append
        _get_theme_style = self._get_theme_style
        for token_type, token in lexer.get_tokens(self.code):
            append(token, _get_theme_style(token_type))
        return text

    def _get_line_numbers_color(self, blend: float = 0.3) -> Color:
        background_color = parse_rgb_hex(
            self._pygments_style_class.background_color[1:]
        )
        foreground_color = self._get_theme_style(Token.Text)._color
        if foreground_color is None:
            return Color.default()
        # TODO: Handle no full colors here
        assert foreground_color.triplet is not None
        new_color = blend_rgb(
            background_color, foreground_color.triplet, cross_fade=blend
        )
        return Color.from_triplet(new_color)

    @property
    def _numbers_column_width(self) -> int:
        """Get the number of characters used to render the numbers column."""
        if self.line_numbers:
            return len(str(self.start_line + self.code.count("\n"))) + 2
        return 0

    def _get_number_styles(self, console: Console) -> Tuple[Style, Style, Style]:
        """Get background, number, and highlight styles for line numbers."""
        background_style = Style(bgcolor=self._pygments_style_class.background_color)
        if console.color_system in ("256", "truecolor"):
            number_style = Style.chain(
                background_style,
                self._get_theme_style(Token.Text),
                Style(color=self._get_line_numbers_color()),
            )
            highlight_number_style = Style.chain(
                background_style,
                self._get_theme_style(Token.Text),
                Style(bold=True, color=self._get_line_numbers_color(0.9)),
            )
        else:
            number_style = highlight_number_style = Style()
        return background_style, number_style, highlight_number_style

    def __measure__(self, console: "Console", max_width: int) -> "Measurement":
        if self.code_width is not None:
            width = self.code_width + self._numbers_column_width
            return Measurement(width, width)
        return Measurement(max_width, max_width)

    def __console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        code_width = options.max_width if self.code_width is None else self.code_width
        code = self.code
        if self.dedent:
            code = textwrap.dedent(code)
        text = self._highlight(self.lexer_name)
        if not self.line_numbers:
            if self.code_width is None:
                yield text
            else:
                yield from console.render(
                    text, options=options.update(width=code_width)
                )
            return

        lines = text.split("\n")

        line_offset = 0
        if self.line_range:
            start_line, end_line = self.line_range
            line_offset = max(0, start_line - 1)
            lines = lines[line_offset:end_line]

        numbers_column_width = self._numbers_column_width
        render_options = options.update(width=code_width + numbers_column_width)

        (
            background_style,
            number_style,
            highlight_number_style,
        ) = self._get_number_styles(console)

        highlight_line = self.highlight_lines.__contains__
        _Segment = Segment
        padding = _Segment(" " * numbers_column_width, background_style)
        new_line = _Segment("\n")

        line_pointer = "❱ "

        for line_no, line in enumerate(lines, self.start_line + line_offset):
            wrapped_lines = console.render_lines(
                line, render_options, style=background_style
            )
            for first, wrapped_line in iter_first(wrapped_lines):
                if first:
                    line_column = str(line_no).rjust(numbers_column_width - 2) + " "
                    if highlight_line(line_no):
                        yield _Segment(line_pointer, number_style)
                        yield _Segment(
                            line_column, highlight_number_style,
                        )
                    else:
                        yield _Segment("  ", highlight_number_style)
                        yield _Segment(
                            line_column, number_style,
                        )
                else:
                    yield padding
                yield from wrapped_line
                yield new_line


if __name__ == "__main__":  # pragma: no cover

    import sys
    from rich.console import Console

    console = Console()

    syntax = Syntax.from_path(sys.argv[1], line_numbers=False)
    console.print(syntax)
