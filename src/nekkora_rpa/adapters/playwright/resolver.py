"""Resolução de um alvo do registro numa página Playwright, com verificação de identidade.

Regras (fail-closed):
- cada candidato (preferido + alternativos) é contado; **qualquer** candidato com 2+ elementos → ``TARGET_AMBIGUOUS``
  (nunca "o primeiro");
- candidatos que acham exatamente um elemento têm de apontar para o MESMO nó; se discordam → ``TARGET_AMBIGUOUS``;
- o nó achado tem de provar a identidade esperada (tag, tipo, papel e nome acessível exato pelo motor ARIA do
  Playwright — só glifos de fonte de ícones nas pontas são ignorados —, documento principal, fora de shadow root);
  senão → ``TARGET_IDENTITY_MISMATCH`` (nó que sai do documento durante a verificação → ``TARGET_DETACHED``,
  transitório);
- nenhum candidato acha nada → espera até o prazo → ``TARGET_NOT_FOUND``.
O resultado é um ``ElementHandle`` preso ao nó verificado: a ação age sobre ESTE nó, não sobre o que o seletor
casar mais tarde (troca de DOM entre verificação e ação vira ``TARGET_DETACHED``, nunca clique em outro elemento).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.sync_api import ElementHandle, Locator, Page
from playwright.sync_api import Error as PlaywrightError

from ...errors.exceptions import PageClosed, TargetAmbiguous, TargetDetached, TargetIdentityMismatch, TargetNotFound
from ...resilience.timing import CancelToken, Clock, Deadline
from ...selectors.schema import Expected, Strategy, Target
from ...selectors.schema import Locator as Ref

# Rótulo visível: associado (labels), aria-labelledby, ou o ÚNICO <label> irmão de um ÚNICO controle no contêiner.
_LABEL_JS = """e => {
  const norm = t => (t || '').replace(/\\s+/g, ' ').trim();
  if (e.labels && e.labels.length === 1) return norm(e.labels[0].textContent);
  if (e.labels && e.labels.length > 1) return null;
  const ids = (e.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
  if (ids.length) return norm(ids.map(i => (document.getElementById(i) || {}).textContent || '').join(' '));
  const p = e.parentElement;
  if (!p) return null;
  const labels = [...p.children].filter(c => c.tagName === 'LABEL');
  const controls = [...p.children].filter(c => ['INPUT', 'TEXTAREA', 'SELECT'].includes(c.tagName));
  if (labels.length === 1 && controls.length === 1 && controls[0] === e) return norm(labels[0].textContent);
  return null;
}"""

_IDENTITY_JS = """e => ({
  tag: e.tagName.toLowerCase(),
  type: (['input', 'button', 'select', 'textarea'].includes(e.tagName.toLowerCase()) ? (e.type || '')
         : (e.getAttribute('type') || '')).toLowerCase(),
  documentScope: e.getRootNode() === e.ownerDocument,
  connected: e.isConnected,
})"""


@dataclass
class Resolution:
    handle: ElementHandle
    strategy_index: int
    """0 = preferido; n = n-ésimo alternativo."""


# Glifo de fonte de ícones (área de uso privado do Unicode, ex.: Font Awesome via ::before) entra no nome acessível
# calculado pelo Playwright, mas não é texto que uma pessoa lê nem que o Studio grava.
_ICON_GLYPHS = r"[\s\ue000-\uf8ff]*"


def accessible_name(name: str | None) -> re.Pattern[str] | None:
    """Nome acessível exato, tolerando só glifos de ícone e espaços nas PONTAS (o texto em si continua exato)."""
    if name is None:
        return None
    return re.compile("^" + _ICON_GLYPHS + re.escape(name) + _ICON_GLYPHS + "$")


def _css_str(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_locator(page: Page, ref: Ref) -> Locator:
    if ref.strategy is Strategy.CSS:
        return page.locator("css=" + (ref.expression or ""))
    if ref.strategy is Strategy.XPATH:
        return page.locator("xpath=" + (ref.expression or ""))
    if ref.strategy is Strategy.ID:
        return page.locator(f"css=[id={_css_str(ref.value or '')}]")
    if ref.strategy is Strategy.NAME:
        return page.locator(f"css=[name={_css_str(ref.value or '')}]")
    if ref.strategy is Strategy.TEST_ID:
        return page.locator(f"css=[data-testid={_css_str(ref.value or '')}]")
    if ref.strategy is Strategy.LABEL:
        text = ref.text or ""
        sibling = (
            "xpath=//*[count(label)=1 and label[normalize-space(.)=" + _xpath_str(text) + "]"
            " and count(input|textarea|select)=1]/*[self::input or self::textarea or self::select]"
        )
        return page.get_by_label(text, exact=True).or_(page.locator(sibling))
    return page.get_by_role(ref.role, name=accessible_name(ref.name))  # type: ignore[arg-type]


def _xpath_str(v: str) -> str:
    if "'" not in v:
        return "'" + v + "'"
    if '"' not in v:
        return '"' + v + '"'
    return "concat(" + ', "\'", '.join("'" + part + "'" for part in v.split("'")) + ")"


def _count(loc: Locator) -> int:
    return loc.count()


def identity_mismatch(page: Page, handle: ElementHandle, expected: Expected) -> str | None:
    """Campo da identidade que divergiu (``tag``, ``type``, ``scope``, ``role``, ``name``) ou ``None``.
    Os valores observados ficam só aqui: nunca são devolvidos nem registrados."""
    info = handle.evaluate(_IDENTITY_JS)
    if not info["connected"]:
        return "detached"
    if info["tag"] != expected.tag:
        return "tag"
    if expected.type is not None and info["type"] != expected.type:
        return "type"
    if not info["documentScope"]:
        return "scope"
    if expected.label is not None and handle.evaluate(_LABEL_JS) != expected.label:
        return "label"
    if expected.role is not None:
        # papel e nome pelo motor ARIA do Playwright, conferidos contra ESTE nó (não contra o que o seletor casar)
        by_role = page.get_by_role(expected.role, include_hidden=True)  # type: ignore[arg-type]
        if not by_role.evaluate_all("(els, h) => els.includes(h)", handle):
            return "role"
        if expected.name is not None:
            # nome EXPOSTO primeiro (o do Chrome e o gravado pelo Studio: sem descendentes aria-hidden, ex.: a seta de
            # "Next <span aria-hidden>→</span>"); com include_hidden=True o Playwright os inclui — só para alvo oculto
            name = accessible_name(expected.name)
            by_name = page.get_by_role(expected.role, name=name)  # type: ignore[arg-type]
            if not by_name.evaluate_all("(els, h) => els.includes(h)", handle):
                by_hidden = page.get_by_role(expected.role, name=name, include_hidden=True)  # type: ignore[arg-type]
                if not by_hidden.evaluate_all("(els, h) => els.includes(h)", handle):
                    return "name"
    return None


class Resolver:
    def __init__(self, clock: Clock, cancel: CancelToken) -> None:
        self.clock = clock
        self.cancel = cancel
        self.rejections: list[tuple[int, str]] = []

    def resolve(self, page: Page, target: Target, deadline: Deadline, *, wait: bool = True) -> Resolution | None:
        """Devolve a resolução, ou ``None`` quando ``wait=False`` e nada foi achado. Lança nos casos proibidos."""
        interval = 0.05
        self.rejections = []
        while True:
            self.cancel.raise_if_cancelled()
            if page.is_closed():
                raise PageClosed(key=target.key)
            found: list[tuple[int, Locator, ElementHandle]] = []
            try:
                for i, ref in enumerate(target.candidates):
                    loc = build_locator(page, ref)
                    n = _count(loc)
                    if n > 1:
                        raise TargetAmbiguous(key=target.key, detail=f"candidate_{i}")
                    if n == 1:
                        handle = loc.element_handle(timeout=max(1, min(deadline.remaining_ms(), 1_000)))
                        if handle is not None:
                            found.append((i, loc, handle))
                if found:
                    return self._verify(page, target, found)
            except PlaywrightError:
                # o nó sumiu entre a contagem e a leitura (DOM em transição) ou a página navegou: conta-se de novo
                for _, _, h in found:
                    _dispose(h)
                if page.is_closed():
                    raise PageClosed(key=target.key) from None
            except BaseException:
                for _, _, h in found:
                    _dispose(h)
                raise
            if not wait or deadline.expired:
                if not wait:
                    return None
                raise TargetNotFound(key=target.key)
            self.clock.sleep(min(interval, deadline.remaining_ms() / 1000.0), self.cancel)
            interval = min(interval * 2, 0.25)

    def _verify(self, page: Page, target: Target, found: list[tuple[int, Locator, ElementHandle]]) -> Resolution:
        first_i, _, first_h = found[0]
        try:
            for _, _, other in found[1:]:
                if not first_h.evaluate("(a, b) => a === b", other):
                    raise TargetAmbiguous(key=target.key, detail="candidates_disagree")
            mismatch = identity_mismatch(page, first_h, target.expected)
        except BaseException:
            for _, _, h in found:
                _dispose(h)
            raise
        for _, _, h in found[1:]:
            _dispose(h)
        if mismatch == "detached":
            # o nó saiu do documento DURANTE a verificação (componente recriado): troca de DOM, não outra identidade —
            # transitório como a troca entre verificação e ação; nada foi feito no nó (NEKKORA-E2E-002)
            _dispose(first_h)
            raise TargetDetached(key=target.key, detail="detached_during_check")
        if mismatch is not None:
            self.rejections.append((first_i, mismatch))
            _dispose(first_h)
            raise TargetIdentityMismatch(key=target.key, detail=mismatch)
        return Resolution(first_h, first_i)


def _dispose(h: ElementHandle) -> None:
    try:
        h.dispose()
    except PlaywrightError:
        pass
