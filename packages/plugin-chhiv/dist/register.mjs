// src/register.ts
var HOST_UI_MODULE = "chhiv-symbol-palette-ui";
async function register(context) {
  context.log("loading CHHIV symbol palette UI from host");
  const ui = await context.loadHostModule(HOST_UI_MODULE);
  if (typeof ui.registerChhivSymbolPaletteUi !== "function") {
    throw new Error(`${HOST_UI_MODULE} is missing registerChhivSymbolPaletteUi`);
  }
  ui.registerChhivSymbolPaletteUi(context);
}
export {
  register
};
//# sourceMappingURL=register.mjs.map
