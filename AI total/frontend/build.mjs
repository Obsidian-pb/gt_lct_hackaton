import {build, context} from 'esbuild';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('.',import.meta.url));
const options={absWorkingDir:root,entryPoints:[root+'src/main.jsx'],tsconfigRaw:{},bundle:true,outfile:'../ui/react/app.js',minify:true,jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'},target:['es2022'],legalComments:'eof'};
if(process.argv.includes('--watch')){const ctx=await context(options);await ctx.watch();console.log('Watching React sources');}else{await build(options);console.log('React build ready: ui/react/app.js');}
