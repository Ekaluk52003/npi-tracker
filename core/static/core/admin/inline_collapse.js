'use strict';
document.addEventListener('DOMContentLoaded', function () {
  const $ = django.jQuery;

  function initCollapse() {
    $('.djn-dynamic-form-core-milestonetemplate').each(function () {
      const $row = $(this);
      if ($row.find('> h3 .collapse-toggle').length) return;

      const $h3 = $row.find('> h3');
      if (!$h3.length) return;

      const $content = $h3.nextAll();
      $content.hide();
      $h3.css('cursor', 'pointer');

      const $toggle = $('<span class="collapse-toggle" style="float:right;font-size:11px;font-weight:normal;padding:2px 6px;background:#ddd;border-radius:3px;margin-left:8px;">[+]</span>');
      $h3.append($toggle);

      $h3.on('click', function (e) {
        if ($(e.target).closest('input, a, label').length) return;
        const collapsed = $content.is(':hidden');
        $content.toggle(collapsed);
        $toggle.text(collapsed ? '[-]' : '[+]');
      });
    });
  }

  initCollapse();

  $(document).on('djnesting:mutate formset:added', function () {
    setTimeout(initCollapse, 50);
  });
});
