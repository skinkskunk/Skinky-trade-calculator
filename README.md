# Skinky Trade Calculator

Dynasty fantasy football trade calculator: values averaged across several free sites, Sleeper roster fit, a trade finder, market signals and the Skinky grade.

## Files

- `index.html`: the app. It already holds a snapshot of every site's values, so it works on its own.
- `values.json`: the latest values from each site. The page reads it every time it opens.
- `update_values.py` and `.github/workflows/update-values.yml`: the daily updater, which runs free on GitHub.
- `netlify_build.py` and `netlify.toml`: only needed if you host on Netlify instead of GitHub Pages.

## Put it online with GitHub Pages

1. Create a **public** repository on github.com.
2. Upload every file in this folder to the top level of the repository, including the hidden `.github` folder. Upload the files themselves, not the folder that contains them.
3. Go to **Settings → Pages**, choose **Deploy from a branch**, then `main` and `/ (root)`, and save.
4. Go to **Settings → Actions → General**, choose **Read and write permissions**, and save.
5. On the **Actions** tab, open **Update trade values** and click **Run workflow**.

The site is at `https://<your-username>.github.io/<repository-name>/`. Every morning the updater refreshes `values.json`, and GitHub republishes the site.
