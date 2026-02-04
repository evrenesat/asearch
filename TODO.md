# TODO


  
- [ ] In session history command we output a nicely formatted
 table but for normal history it is still using old simpler uglier table and actually currently it's even broken it works but it looks weird so please update history output history command
 just like session history you display as much as possible data from the table that is relevant to list of individual messages.

- Tool: link_extractor
This is an experimental tool. When we give this tool accept URLs and returns all the links and only links to the model. Links and their labels.
 But we store textual body of the content in the database as a cache for the URL. But we don't share it immediately with the model. Instead we share the links with the model. And we ask model again if it wants to
 retrieve more links from those links more deep into the links. If it decides if it wants it provides back more links and we retrieve those links as well.
 And again we return only links. But we extract text bodies of the content and store them in the database as a cache again.

 - [] Read custom prompt from file path

 - [] I want to introduce a data_push tool for making get or post request to any URLs with the final result.


```toml

[push_data.post_to_my_blog]
method = "post" # or get
[push_data.post_to_my_blog.fields]
username=my_bot
password_env=""

```

