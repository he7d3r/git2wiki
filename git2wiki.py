#!/usr/bin/python
# -*- coding: utf-8  -*-
""" Script to sync git repositories with wiki pages """
# Requirements
# sudo npm install uglify-js -g
# sudo pip install PyExecJS
# sudo pip install uglipyjs

import pywikibot
import os
import execjs
import uglipyjs
import pkg_resources
import re


def main(*args):
    tracking = False
    gitHubUser = False
    repo = False
    rootDir = os.getcwd()
    gitHubUrl = 'https://github.com/%s'
    # FIXME: Add git hash/version as in
    # "Sync with https://github.com/FOO/BAR (v9.9.9 or HASH)"
    gitHubSummary = 'Sync with %s'
    # FIXME: Add UglifyJS version as in
    # "minify with UglifyJS v9.9.9"
    uglifyjsSummary = 'minify with UgliPyJS %s'
    for arg in pywikibot.handle_args():
        if arg == "-all":
            allowNullEdits = True
        elif arg == "-track":
            # The file link is unnecessary on GitHub but useful on wiki
            tracking = '[[File:%s]] (workaround for [[phab:T35355]])'
        elif arg.startswith('-prefix:'):
            userPrefix = arg[len('-prefix:'):]
        elif arg.startswith('-repo:'):
            repo = arg[len('-repo:'):]
        elif arg.startswith('-mypath:'):
            rootDir = arg[len('-mypath:'):]
        elif arg.startswith('-github:'):
            gitHubUser = arg[len('-github:'):]
    if not gitHubUser:
        print('Missing required paramenter -github:<username>.')
        return
    gitHubUrl = (gitHubUrl % gitHubUser) + '/%s'
    site = pywikibot.Site()  # pywikibot.Site( 'meta', 'meta' )
    for dirpath, dirnames, files in os.walk(rootDir):
        for name in files:
            ext = name.rsplit('.', 1)[-1].lower()
            # Assume the structure is <mypath>/<repo>/src/<title.(js|css)>
            if (ext in ['js', 'css'] and
                    dirpath.endswith('/src') and
                    (not repo or repo in name)):
                # FIXME: Skip unchanged files (use git status?)
                # Check for allowNullEdits
                title = userPrefix + name
                repoName = dirpath.rsplit('/', 2)[-2]
                summary = gitHubSummary % (gitHubUrl % repoName)
                code = open(os.path.join(dirpath, name), 'r').read()
                if ext == 'js':
                    try:
                        minCode = uglipyjs.compile(
                            code, {'preserveComments': 'some'})
                        minCode = minCode.decode('utf-8')
                        # summary = summary + '; ' + uglifyjsSummary %
                        # (pkg_resources.get_distribution("uglipyjs").version)
                        uv = pkg_resources.get_distribution("uglipyjs").version
                        summary = '{}; {}'.format(
                            summary, uglifyjsSummary % uv)
                    except execjs.ProgramError:
                        minCode = code.decode('utf-8')
                    newMinCode = re.sub(
                        r'(/\*\*\n \*.+? \*/\n)',
                        r'\1// <nowiki>\n',
                        minCode,
                        flags=re.DOTALL)
                    if newMinCode == minCode:
                        newMinCode = '// <nowiki>\n' + minCode
                    minCode = newMinCode + '\n// </nowiki>'
                    if tracking:
                        minCode = '// ' + (tracking % title) + '\n' + minCode
                else:
                    minCode = '/* <nowiki> */\n' + code + '\n/* </nowiki> */'
                    if tracking:
                        # minCode = '/* ' + (tracking % title) +
                        # ' */\n' + minCode
                        minCode = '/* {} */\n{}'.format(
                            tracking % title, minCode)
                page = pywikibot.Page(site, title)
                page.text = minCode
                page.save(summary)
    page = pywikibot.Page(site, 'User:He7d3r/global.js')
    page.text = ('// [[File:User:He7d3r/global.js]] (workaround for'
                 ' [[phab:T35355]])\n//{ {subst:User:He7d3r/Tools.js}}\n'
                 '{{subst:User:He7d3r/Tools.js}}')
    page.save('Update')


if __name__ == '__main__':
    main()
