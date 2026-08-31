// src/register.ts
var HOST_UI_MODULE = "bdrc-import-ui";
async function register(context) {
  context.log("loading BDRC import UI from host");
  const ui = await context.loadHostModule(HOST_UI_MODULE);
  if (typeof ui.registerBdrcImportUi !== "function") {
    throw new Error(`${HOST_UI_MODULE} is missing registerBdrcImportUi`);
  }
  ui.registerBdrcImportUi(context);
}
export {
  register
};
//# sourceMappingURL=register.mjs.map
