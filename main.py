from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Literal, Self

import coloraide
import cyclopts
import msgspec
import rich
from coloraide.spaces.okhsl import Okhsl
from coloraide.spaces.okhsv import Okhsv


class _Color(coloraide.Color): ...


_Color.register(Okhsl())
_Color.register(Okhsv())

_DEFAULT_COLOR = _Color('okhsl', [0, 0, 0], alpha=0)


class Edit(msgspec.Struct):
    variable: str
    value: float
    type: Literal['value', 'add', 'multiply'] = 'value'

    name: str | None = None
    accent: bool | None = None

    _inverse_light: bool = False

    def __call__(self, value: float) -> float:
        inverse = self._inverse_light and self.variable in {'l', 'lightness'}

        match self.type:
            case 'value':
                return self.value
            case 'add':
                v = -self.value if inverse else self.value
                return value + v
            case 'multiply':
                v = 1.0 / self.value if inverse else self.value
                return value * v


class Config(msgspec.Struct):
    color_space: str = 'okhsl'
    inverse_edit_light: bool = True

    edits: list[Edit] = []


class Color(msgspec.Struct):
    hex: str
    accent: bool

    color: _Color = _DEFAULT_COLOR

    def __post_init__(self) -> None:
        self.color = _Color(self.hex).convert('okhsl')  # type: ignore[assignment]

    def edit(self, key: str, value: float | Callable[[float], float]) -> None:
        self.color.set(key, value)

    def update(self) -> None:
        self.hex = self.color.convert('srgb').to_string(hex=True)


class Palette(msgspec.Struct):
    name: str
    dark: bool
    colors: dict[str, Color]

    def to_hex(self) -> Self:
        def colors() -> Iterable[tuple[str, str]]:
            for name, color in self.colors.items():
                yield name, f'{color.hex}ff'

        return msgspec.structs.replace(self, colors=dict(colors()))

    def edit(self, conf: Config) -> None:
        inverse = conf.inverse_edit_light and not self.dark
        edits = tuple(
            msgspec.structs.replace(x, _inverse_light=inverse) for x in conf.edits
        )

        for name, color in self.colors.items():
            color.color = color.color.convert(conf.color_space)  # type: ignore[assignment]

            for edit in edits:
                if edit.name == name or edit.accent == color.accent:
                    color.edit(edit.variable, edit)

        for color in self.colors.values():
            color.update()


class Palettes(msgspec.Struct):
    version: str

    latte: Palette
    frappe: Palette
    macchiato: Palette
    mocha: Palette

    def palettes(self) -> Iterator[tuple[str, Palette]]:
        for field in msgspec.structs.fields(self):
            if field.type is Palette:
                yield field.name, getattr(self, field.name)


def read_palettes(path: Path) -> Palettes:
    return msgspec.json.decode(path.read_bytes(), type=Palettes, strict=False)


class JsonEncoder:
    def __init__(self, *, detailed: bool = False) -> None:
        self.detailed = detailed

    def enc_hook(self, obj: object) -> str:
        if isinstance(obj, _Color):
            return str(obj)

        raise NotImplementedError

    def _palettes(self, p: Palettes) -> Palettes:
        if self.detailed:
            return p

        return msgspec.structs.replace(
            p, **{k: v.to_hex().colors for k, v in p.palettes()}
        )

    def encode(self, p: Palettes) -> bytes:
        obj = self._palettes(p)
        return msgspec.json.encode(obj, enc_hook=self.enc_hook)

    def write(self, p: Palettes, path: Path, suffix: str | None = None) -> None:
        if suffix:
            path = path.with_name(f'{path.stem}-{suffix}').with_suffix('.json')

        buf = self.encode(p)
        buf = msgspec.json.format(buf)
        path.write_bytes(buf)


app = cyclopts.App()


@app.default
def main(
    input_: Path = Path('palette.json'),
    output: Path = Path('output'),
    *,
    config: Path = Path('config.toml'),
    detailed: bool = False,
) -> None:
    conf = msgspec.toml.decode(config.read_bytes(), type=Config)
    encoder = JsonEncoder(detailed=detailed)

    palettes = read_palettes(input_)
    encoder.write(palettes, path=output, suffix='original')

    for _, palette in palettes.palettes():
        palette.edit(conf)

    encoder.write(palettes, path=output, suffix='customized')

    rich.print(palettes)


if __name__ == '__main__':
    app()
