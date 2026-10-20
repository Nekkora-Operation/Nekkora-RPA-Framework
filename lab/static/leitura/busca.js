// Laboratório genérico de LEITURA (dados fictícios): campo de busca que o "componente" RECRIA ao receber foco (o nó
// original some e o novo não tem id) — como bibliotecas de interface fazem — e uma cópia oculta no cabeçalho fixo.
(() => {
  const FICHAS = {'ana exemplo': 'ficha-ana.html', 'bruno modelo': 'ficha-bruno.html', 'carla teste': 'ficha-carla.html',
    'davi amostra': 'ficha-davi.html', 'eva formula': 'ficha-eva.html',
    'fabio ficticio': 'ficha-fabio.html', 'gina inventada': 'ficha-gina.html'};
  const form = document.getElementById('buscaform');
  const montar = () => {
    const velho = document.getElementById('campo-busca');
    if (!velho) return;
    const novo = document.createElement('input');
    novo.type = 'search'; novo.name = 'q'; novo.autocomplete = 'off';
    novo.setAttribute('role', 'combobox'); novo.setAttribute('aria-label', 'Pesquisar no acervo');
    velho.replaceWith(novo);
    setTimeout(() => novo.focus(), 0);
  };
  document.getElementById('campo-busca').addEventListener('focus', montar, {once: true});
  form.addEventListener('submit', ev => {
    ev.preventDefault();
    const q = form.querySelector('input[name=q]').value.trim().toLowerCase();
    location.href = '/leitura/' + (FICHAS[q] || 'nada.html');
  });
})();
