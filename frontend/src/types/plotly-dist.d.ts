// plotly.js-dist-min ships no type declarations of its own;
// re-use the @types/plotly.js typings for the bundled distribution.
declare module "plotly.js-dist-min" {
  import * as Plotly from "plotly.js";
  export = Plotly;
}
